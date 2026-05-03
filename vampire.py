#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
 ██╗   ██╗ █████╗ ███╗   ███╗██████╗ ██╗██████╗ ██╗ ██████╗
 ██║   ██║██╔══██╗████╗ ████║██╔══██╗██║██╔══██╗██║██╔════╝
 ██║   ██║███████║██╔████╔██║██████╔╝██║██████╔╝██║██║
 ╚██╗ ██╔╝██╔══██║██║╚██╔╝██║██╔═══╝ ██║██╔══██╗██║██║
  ╚████╔╝ ██║  ██║██║ ╚═╝ ██║██║     ██║██║  ██║██║╚██████╗
   ╚═══╝  ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝ ╚═════╝
  ██████╗██████╗  █████╗ ██╗    ██╗██╗     ███████╗██████╗
 ██╔════╝██╔══██╗██╔══██╗██║    ██║██║     ██╔════╝██╔══██╗
 ██║     ██████╔╝███████║██║ █╗ ██║██║     █████╗  ██████╔╝
 ██║     ██╔══██╗██╔══██║██║███╗██║██║     ██╔══╝  ██╔══██╗
 ╚██████╗██║  ██║██║  ██║╚███╔███╔╝███████╗███████╗██║  ██║
  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚══╝╚══╝ ╚══════╝╚══════╝╚═╝  ╚═╝
"""
from __future__ import print_function

import argparse
import io
import json
import os
import random
import re
import sys
import threading
import time
import warnings
from urllib.parse import urlparse, urlsplit

warnings.filterwarnings('ignore')

from core.colors import (
    blood, fang, coffin, crypt, moon,
    dark_red, green, end, bold,
)
from core.checkpoint import load_checkpoint, normalize_checkpoint_sets, save_checkpoint
from core.checkpoint import normalize_checkpoint_mapping
import core.config
from core.autopsy import (
    ANALYSIS_DATASET_NAMES,
    anatomy_lines,
    build_autopsy,
    build_mutation_probes,
    build_site_anatomy,
    finalize_genealogy,
    genealogy_lines,
    mutation_lines,
    record_artifact_discovery,
    update_artifact_observation,
    write_autopsy_files,
)
from core.config import INTELS
from core.extractors import run_page_extractors, run_script_extractors
from core.flash import flash
from core.modes import (
    DOCUMENT_EXTENSIONS,
    MODE_DATASET_NAMES,
    PRESET_DEFINITIONS,
    RITUAL_CHAIN_DEFINITIONS,
    build_hidden_candidates,
    build_temporal_diffs,
    coerce_preset,
    coerce_ritual_chain,
    coerce_mode,
    extract_document_records,
)
from core.politeness import PolitenessController
from core.render import render_page
from core.requester import requester, get_session
from core.utils import (
    CrawlStats,
    extract_headers,
    is_in_scope,
    normalize_fuzzable_url,
    normalize_url,
    normalize_content_type,
    proxy_type,
    remove_regex,
    should_extract_markup,
    should_extract_script,
    timer,
    top_level,
    verb,
    writer,
    luhn,
    is_good_proxy,
)
from core.zap import zap
from core.specimen import (
    SPECIMEN_KIND_CHOICES,
    apply_preset,
    classify_specimen,
    resolve_ritual_plan,
    setup_status,
)


def _configure_console_stream(stream):
    if stream is None:
        return stream
    try:
        stream.reconfigure(errors='replace')
        return stream
    except (AttributeError, ValueError):
        buffer = getattr(stream, 'buffer', None)
        if buffer is None:
            return stream
        return io.TextIOWrapper(
            buffer,
            encoding=getattr(stream, 'encoding', None) or 'utf-8',
            errors='replace',
            line_buffering=True,
        )


sys.stdout = _configure_console_stream(sys.stdout)
sys.stderr = _configure_console_stream(sys.stderr)

BANNER = f"""
{dark_red}🦇 Vampiric Crawler{end}  {crypt}v1.1.0{end}
{crypt}The Gothic Web Stalker — clear first, gothic second.{end}
"""
print(BANNER)

if sys.version_info < (3, 6):
    print(f'{coffin}Vampiric Crawler requires Python 3.6+. Your mortal Python is too old.')
    sys.exit(1)


parser = argparse.ArgumentParser(
    description='Vampiric Crawler — a gothic OSINT web spider',
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument('-u', '--url', help='Target URL (the prey)', dest='root', required=False)
parser.add_argument('--target', help='Target specimen (URL, domain, PDF, JS file, HTML paste, handle, or company name)')
parser.add_argument('-l', '--level', help='Depth of the hunt (default: 2)', dest='level', type=int, default=2)
parser.add_argument('-t', '--threads', help='Number of simultaneous fangs (default: 4)', dest='threads', type=int, default=4)
parser.add_argument('-d', '--delay', help='Delay between feedings in seconds (default: 0)', dest='delay', type=float, default=0)
parser.add_argument('--timeout', help='HTTP request timeout in seconds (default: 8)', dest='timeout', type=float, default=8)
parser.add_argument('-s', '--seeds', help='Additional seed URLs to begin the hunt', dest='seeds', nargs='+', default=[])
parser.add_argument('-r', '--regex', help='Custom regex pattern to extract from pages', dest='regex')
parser.add_argument('--exclude', help='Exclude URLs matching this regex pattern', dest='exclude')
parser.add_argument('-o', '--output', help='Output directory for the harvested blood (loot)', dest='output')
parser.add_argument('-e', '--export', help='Also export results as this format', dest='export', choices=['csv', 'json'])
parser.add_argument('--stdout', help='Print a specific dataset to stdout (e.g. internal)', dest='std')
parser.add_argument('-c', '--cookie', help='Cookie header value', dest='cook')
parser.add_argument('--user-agent', help='Custom user agent string(s), comma-separated', dest='user_agent')
parser.add_argument('-H', '--header', '--headers', help='Custom header in Key: Value form (repeatable)', dest='headers', action='append', default=[])
parser.add_argument('-p', '--proxy', help='Proxy or proxies in HOST:PORT format (comma-separated)', dest='proxies', type=proxy_type)
parser.add_argument('--keys', help='Extract high-entropy strings (API keys, tokens)', dest='api', action='store_true')
parser.add_argument('--dns', help='Enumerate subdomains and dump DNS data', dest='dns', action='store_true')
parser.add_argument('--wayback', help='Fetch archived URLs from archive sources as extra seeds', dest='archive', action='store_true')
parser.add_argument('--only-urls', help='Only harvest URLs, skip intel extraction', dest='only_urls', action='store_true')
parser.add_argument('--scope', help='Scope of the hunt: exact host or full registered domain', dest='scope', choices=['host', 'domain'], default='host')
parser.add_argument('--scope-allow', help='Extra regex that URLs must match to stay in scope (repeatable)', action='append', default=[])
parser.add_argument('--scope-deny', help='Regex that forces URLs out of scope even if host/domain matches (repeatable)', action='append', default=[])
parser.add_argument('--mode', help='Focused crawl mode override', choices=['generic', 'document', 'js-intel', 'forum', 'geo', 'news', 'hidden', 'scam', 'temporal'])
parser.add_argument('--ritual-chain', help='Higher-level crawl workflow', choices=sorted(RITUAL_CHAIN_DEFINITIONS))
parser.add_argument('--preset', help='Preset crawl configuration', choices=sorted(PRESET_DEFINITIONS), default='balanced')
parser.add_argument('--input-kind', help='Force specimen classification', choices=SPECIMEN_KIND_CHOICES, default='auto')
parser.add_argument('--dry-run', help='Show the resolved crawl plan without making requests', action='store_true')
parser.add_argument('--setup-check', help='Check Python and Playwright prerequisites, then exit', action='store_true')
parser.add_argument('--render-js', help='Render pages in headless Chromium before extraction', action='store_true')
parser.add_argument('--render-timeout', help='Per-page render timeout in seconds (default: 12)', type=float, default=12)
parser.add_argument('--checkpoint', help='Write crawl state to this checkpoint file')
parser.add_argument('--resume', help='Resume a previous crawl from this checkpoint file')
parser.add_argument('--temporal-baseline', help='Directory containing a prior crawl snapshot for temporal diff mode')
parser.add_argument('--respect-robots-delay', help='Honor robots.txt Crawl-delay when present', action='store_true')
parser.add_argument('--host-concurrency', help='Maximum concurrent requests per host (default: 2)', type=int, default=2)
parser.add_argument('--disable-adaptive-backoff', help='Disable automatic backoff on 429/503 responses', action='store_true')
parser.add_argument('-v', '--verbose', help='Show every drop of blood (verbose output)', dest='verbose', action='store_true')
args = parser.parse_args()

if args.setup_check:
    status = setup_status()
    print(f'{fang}First-run setup check')
    print(f'{crypt}Install Python deps: {status["install_hint"]}')
    print(f'{crypt}Install browser:    {status["browser_hint"]}')
    for module_name, module_status in sorted(status['packages'].items()):
        print(f'{fang}{module_name:<12} {module_status}')
    print(f'{fang}playwright-browser {status["playwright_browser"]}')
    sys.exit(0 if all(value == 'ok' for value in status['packages'].values()) and status['playwright_browser'] == 'ok' else 1)

resume_state = None
if args.resume:
    try:
        resume_state = load_checkpoint(args.resume)
    except Exception as exc:
        print(f'{coffin}Could not resume from checkpoint: {exc}')
        sys.exit(1)
    if not args.root and not args.target:
        args.root = resume_state.get('main_url')

target_input = args.target or args.root or (resume_state.get('specimen_input') if resume_state else '')
if not target_input:
    print(f'\n{coffin}No prey specified. Use {bold}-u <URL>{end} or {bold}--target <SPECIMEN>{end} to choose a target.\n')
    parser.print_help()
    sys.exit(1)

core.config.verbose = args.verbose
verbose = args.verbose
cook = args.cook or None
checkpoint_path = args.checkpoint or args.resume
temporal_baseline = args.temporal_baseline


def cli_arg_present(*names):
    return any(name in sys.argv[1:] for name in names)


specimen_kind = (
    resume_state.get('specimen_kind')
    if resume_state and not cli_arg_present('--input-kind') and args.input_kind == 'auto'
    else args.input_kind
)
specimen_profile = (
    resume_state.get('specimen_profile')
    if resume_state and not cli_arg_present('--input-kind', '--target', '-u', '--url')
    else classify_specimen(target_input, specimen_kind)
)
ritual_plan = resolve_ritual_plan(
    specimen_profile,
    ritual_chain=(resume_state.get('ritual_chain') if resume_state and not cli_arg_present('--ritual-chain') else args.ritual_chain),
    mode_override=(resume_state.get('mode') if resume_state and not cli_arg_present('--mode') else args.mode),
)
ritual_chain = str(ritual_plan['ritual_chain'])

explicit_options = set()
for names, key in (
    (('-l', '--level'), 'depth'),
    (('-t', '--threads'), 'threads'),
    (('-d', '--delay'), 'delay'),
    (('--timeout',), 'timeout'),
    (('--scope',), 'scope'),
    (('--keys',), 'extract_secrets'),
    (('--only-urls',), 'only_urls'),
    (('--wayback',), 'archive_seeds'),
    (('--render-js',), 'render_js'),
    (('--respect-robots-delay',), 'respect_robots_delay'),
):
    if cli_arg_present(*names):
        explicit_options.add(key)

resolved_config = {
    'depth': args.level,
    'threads': args.threads,
    'delay': args.delay,
    'timeout': args.timeout,
    'scope': args.scope,
    'extract_secrets': bool(args.api),
    'only_urls': bool(args.only_urls),
    'archive_seeds': bool(args.archive),
    'render_js': bool(args.render_js),
    'respect_robots_delay': bool(args.respect_robots_delay),
}
for key, value in ritual_plan.get('defaults', {}).items():
    if key not in explicit_options:
        resolved_config[key] = value
resolved_config = apply_preset(
    resolved_config,
    (resume_state.get('preset') if resume_state and not cli_arg_present('--preset') else args.preset),
    explicit_options,
)

delay = float(resolved_config['delay'])
timeout = float(resolved_config['timeout'])
api = bool(resolved_config['extract_secrets'])
only_urls = bool(resolved_config['only_urls'])
crawl_level = int(resolved_config['depth'])
thread_count = int(resolved_config['threads'])
scope_mode = str(resolved_config['scope'])
mode = coerce_mode(ritual_plan['mode'])
preset = coerce_preset(resolved_config.get('preset'))
document_depth_forced = mode == 'document' and crawl_level < 1
args.archive = bool(resolved_config.get('archive_seeds'))
args.render_js = bool(resolved_config.get('render_js'))
args.respect_robots_delay = bool(resolved_config.get('respect_robots_delay'))
dataset_names = [
    'files', 'forms', 'intel', 'robots', 'custom', 'failed', 'skipped',
    'redirects', 'internal', 'scripts', 'external', 'fuzzable',
    'endpoints', 'keys', *MODE_DATASET_NAMES, *ANALYSIS_DATASET_NAMES,
]

if mode == 'js-intel':
    api = True
if mode == 'document':
    crawl_level = max(crawl_level, 1)


def compile_patterns(patterns, label):
    compiled = []
    for pattern in patterns or ():
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            print(f'{coffin}Malformed {label} tribute: {exc}')
            sys.exit(1)
    return tuple(compiled)


scope_allow = compile_patterns(args.scope_allow, 'scope allow regex')
scope_deny = compile_patterns(args.scope_deny, 'scope deny regex')

try:
    headers = extract_headers('\n'.join(args.headers))
except ValueError as exc:
    print(f'{coffin}Malformed header tribute: {exc}')
    sys.exit(1)

proxies = []
if args.proxies:
    print(f'{fang}Testing {len(args.proxies)} proxy/proxies — patience, the night is long…')
    for proxy in args.proxies:
        if is_good_proxy(proxy):
            proxies.append(proxy)
        else:
            print(f'{coffin}Proxy unreachable: {proxy}')
    if not proxies:
        print(f'{coffin}No working proxies found. Emerging from the shadows anyway…')
        proxies.append(None)
else:
    proxies.append(None)

direct_local_html = specimen_profile.get('type') == 'html' and bool(specimen_profile.get('inline_payload'))
direct_local_js = specimen_profile.get('type') == 'js' and bool(specimen_profile.get('local_path'))
direct_local_pdf = specimen_profile.get('type') == 'pdf' and bool(specimen_profile.get('local_path'))
direct_remote_js = specimen_profile.get('type') == 'js' and not bool(specimen_profile.get('local_path'))
direct_remote_pdf = specimen_profile.get('type') == 'pdf' and not bool(specimen_profile.get('local_path'))

if resume_state:
    main_url = resume_state.get('main_url') or ''
    requested_root = normalize_url(target_input) if target_input and target_input.startswith('http') else ''
    if requested_root and main_url and requested_root != main_url and not direct_remote_js and not direct_remote_pdf:
        print(f'{coffin}Checkpoint prey mismatch: {requested_root} != {main_url}')
        sys.exit(1)
else:
    main_url = ''
    specimen_root = ''
    roots = list(specimen_profile.get('crawl_roots') or ())
    if specimen_profile.get('type') == 'sitemap' and ritual_plan.get('seed_urls'):
        specimen_root = ritual_plan['seed_urls'][-1]
    elif direct_remote_js or direct_remote_pdf:
        direct_url = roots[0] if roots else ''
        parsed_direct = urlsplit(direct_url)
        specimen_root = normalize_url(f'{parsed_direct.scheme}://{parsed_direct.netloc}/') if parsed_direct.scheme and parsed_direct.netloc else ''
    elif roots:
        specimen_root = roots[0]
    if specimen_root:
        if specimen_root.startswith('http'):
            main_url = normalize_url(specimen_root)
        else:
            try:
                probe_proxy = random.choice(proxies) if proxies else None
                get_session().get('https://' + specimen_root, proxies=probe_proxy, timeout=timeout, verify=False, headers=headers or None)
                main_url = normalize_url('https://' + specimen_root)
            except Exception:
                main_url = normalize_url('http://' + specimen_root)

if not main_url and not (direct_local_html or direct_local_js or direct_local_pdf):
    if args.dry_run:
        main_url = ''
    else:
        print(f'{coffin}The chosen specimen was classified as {specimen_profile.get("type")} but could not be normalized into a crawlable URL.')
        sys.exit(1)

if args.dry_run:
    print(f'{fang}Dry run — no requests will be made.')
    print(f'{fang}Specimen type   {specimen_profile.get("type")}')
    print(f'{fang}Ritual chain    {ritual_chain}')
    print(f'{fang}Mode            {mode}')
    print(f'{fang}Preset          {preset}')
    print(f'{fang}Main root       {main_url or "-"}')
    print(f'{fang}Seed roots      {", ".join(ritual_plan.get("seed_urls") or []) or "-"}')
    print(f'{fang}Scope           {scope_mode}')
    print(f'{fang}Depth           {crawl_level}')
    print(f'{fang}Threads         {thread_count}')
    print(f'{fang}Delay           {delay}')
    print(f'{fang}Timeout         {timeout}')
    print(f'{fang}Archive seeds   {str(bool(resolved_config.get("archive_seeds"))).lower()}')
    print(f'{fang}Render JS       {str(bool(resolved_config.get("render_js"))).lower()}')
    print(f'{fang}Secrets         {str(api).lower()}')
    if specimen_profile.get('notes'):
        for note in specimen_profile['notes']:
            print(f'{crypt}{note}')
    sys.exit(0)

host = urlparse(main_url).netloc
try:
    domain = top_level(main_url)
except Exception:
    domain = host
output_dir = args.output or (resume_state.get('output_dir') if resume_state else None) or (host or 'specimen')

if args.user_agent:
    user_agents = [ua.strip() for ua in args.user_agent.split(',') if ua.strip()]
else:
    ua_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'core', 'user-agents.txt')
    try:
        with open(ua_file, 'r', encoding='utf-8') as handle:
            user_agents = [line.strip() for line in handle if line.strip()]
    except FileNotFoundError:
        user_agents = ['Mozilla/5.0 (compatible; VampiricCrawler/1.0)']

stats = CrawlStats()
files = set()
forms = set()
intel = set()
robots = set()
custom = set()
failed = set()
skipped = set()
redirects = set()
internal = set()
scripts = set()
external = set()
fuzzable = set()
endpoints = set()
keys = set()
document_metadata = set()
document_leaks = set()
js_intel = set()
threads = set()
locations = set()
stories = set()
hidden_paths = set()
scam_signals = set()
temporal_diffs = set()
site_anatomy = set()
mutation_probes = set()
processed = set()
bad_scripts = set()
bad_intel = set()
artifact_genealogy = {}
content_types = {}
render_state = {'disabled': False, 'message': None}
render_lock = threading.Lock()
runtime_state_lock = threading.Lock()
queue_state = {
    'pending': set(),
    'active': set(),
    'completed': set(),
    'skipped': set(),
}
crawl_records = {}
discovery_counter = {'value': 0}
robots_metadata = {'rules': [], 'crawl_delay': None}
sitemap_metadata = {'sitemap_urls': [], 'queued_urls': []}
webui_events_enabled = os.environ.get('VAMPIRIC_WEBUI_EVENTS') == '1'

if resume_state:
    restored = normalize_checkpoint_sets(resume_state)
    files.update(restored['files'])
    forms.update(restored['forms'])
    intel.update(restored['intel'])
    robots.update(restored['robots'])
    custom.update(restored['custom'])
    failed.update(restored['failed'])
    skipped.update(restored['skipped'])
    redirects.update(restored['redirects'])
    internal.update(restored['internal'])
    scripts.update(restored['scripts'])
    external.update(restored['external'])
    fuzzable.update(restored['fuzzable'])
    endpoints.update(restored['endpoints'])
    keys.update(restored['keys'])
    document_metadata.update(restored['document_metadata'])
    document_leaks.update(restored['document_leaks'])
    js_intel.update(restored['js_intel'])
    threads.update(restored['threads'])
    locations.update(restored['locations'])
    stories.update(restored['stories'])
    hidden_paths.update(restored['hidden_paths'])
    scam_signals.update(restored['scam_signals'])
    temporal_diffs.update(restored['temporal_diffs'])
    site_anatomy.update(restored['site_anatomy'])
    mutation_probes.update(restored['mutation_probes'])
    processed.update(restored['processed'])
    bad_scripts.update(restored['bad_scripts'])
    bad_intel.update(restored['bad_intel'])
    artifact_genealogy.update(normalize_checkpoint_mapping(resume_state, 'artifact_genealogy'))
    content_types.update(normalize_checkpoint_mapping(resume_state, 'content_types'))
    stats = CrawlStats.from_snapshot(resume_state.get('stats'))
    restored_queue_state = normalize_checkpoint_mapping(resume_state, 'queue_state')
    for state_name in queue_state:
        queue_state[state_name].update(str(item) for item in restored_queue_state.get(state_name, []) if item)
    restored_crawl_records = normalize_checkpoint_mapping(resume_state, 'crawl_records')
    for record_url, record in restored_crawl_records.items():
        if not isinstance(record, dict):
            continue
        crawl_records[str(record_url)] = {
            'url': str(record.get('url') or record_url),
            'status_code': record.get('status_code'),
            'content_type': str(record.get('content_type') or ''),
            'depth': record.get('depth'),
            'source_page': str(record.get('source_page') or ''),
            'discovery_time': int(record.get('discovery_time') or 0),
            'state': str(record.get('state') or 'pending'),
            'error_kind': str(record.get('error_kind') or ''),
            'error_message': str(record.get('error_message') or ''),
            'source_kind': str(record.get('source_kind') or ''),
        }
        discovery_counter['value'] = max(discovery_counter['value'], crawl_records[str(record_url)]['discovery_time'])
    restored_robots_metadata = normalize_checkpoint_mapping(resume_state, 'robots_metadata')
    if restored_robots_metadata:
        robots_metadata.update({
            'rules': list(restored_robots_metadata.get('rules') or []),
            'crawl_delay': restored_robots_metadata.get('crawl_delay'),
        })
    restored_sitemap_metadata = normalize_checkpoint_mapping(resume_state, 'sitemap_metadata')
    if restored_sitemap_metadata:
        sitemap_metadata.update({
            'sitemap_urls': list(restored_sitemap_metadata.get('sitemap_urls') or []),
            'queued_urls': list(restored_sitemap_metadata.get('queued_urls') or []),
        })

policy = PolitenessController(
    base_delay=delay,
    host_concurrency=args.host_concurrency,
    adaptive_backoff=not args.disable_adaptive_backoff,
)


def emit_webui_event(event_type, payload):
    if not webui_events_enabled:
        return
    print(f'[WEBUI]{json.dumps({"type": event_type, "payload": payload}, sort_keys=True, ensure_ascii=False)}', flush=True)


def _queue_snapshot_locked(limit=12):
    return {
        name: {
            'count': len(values),
            'items': sorted(values)[:limit],
        }
        for name, values in queue_state.items()
    }


def finalize_crawl_records():
    records = {}
    for url, record in crawl_records.items():
        records[url] = {
            'url': url,
            'status_code': record.get('status_code'),
            'content_type': record.get('content_type') or '',
            'depth': record.get('depth'),
            'source_page': record.get('source_page') or '',
            'discovery_time': int(record.get('discovery_time') or 0),
            'state': record.get('state') or 'pending',
            'error_kind': record.get('error_kind') or '',
            'error_message': record.get('error_message') or '',
            'source_kind': record.get('source_kind') or '',
        }
    return records


def emit_queue_snapshot():
    with runtime_state_lock:
        snapshot = _queue_snapshot_locked()
    emit_webui_event('queue', snapshot)


def upsert_crawl_record(url, source_page=None, source_kind=None, depth=None, state=None,
                        status_code=None, content_type=None, error_kind=None, error_message=None):
    if not url:
        return {}
    with runtime_state_lock:
        record = crawl_records.setdefault(url, {
            'url': url,
            'status_code': None,
            'content_type': '',
            'depth': None,
            'source_page': '',
            'discovery_time': 0,
            'state': 'pending',
            'error_kind': '',
            'error_message': '',
            'source_kind': '',
        })
        if not record['discovery_time']:
            discovery_counter['value'] += 1
            record['discovery_time'] = discovery_counter['value']
        if source_page and not record.get('source_page'):
            record['source_page'] = source_page
        if source_kind and not record.get('source_kind'):
            record['source_kind'] = source_kind
        if depth is not None:
            record['depth'] = depth
        if state:
            record['state'] = state
        if status_code is not None:
            record['status_code'] = status_code
        if content_type is not None:
            record['content_type'] = content_type or ''
        if error_kind is not None:
            record['error_kind'] = error_kind or ''
        if error_message is not None:
            record['error_message'] = error_message or ''
        snapshot = dict(record)
    emit_webui_event('result', snapshot)
    return snapshot


def note_pending_url(url, source_page=None, source_kind='link'):
    if not url:
        return
    upsert_crawl_record(url, source_page=source_page, source_kind=source_kind, state='pending')
    with runtime_state_lock:
        if url not in queue_state['active'] and url not in queue_state['completed'] and url not in queue_state['skipped']:
            queue_state['pending'].add(url)
    emit_queue_snapshot()


def mark_active_url(url):
    if not url:
        return
    with runtime_state_lock:
        queue_state['pending'].discard(url)
        queue_state['active'].add(url)
    upsert_crawl_record(url, state='active')
    emit_queue_snapshot()


def finalize_url_state(url, terminal_state, *, status_code=None, content_type=None,
                       error_kind=None, error_message=None):
    if not url:
        return
    queue_terminal_state = 'skipped' if terminal_state == 'skipped' else 'completed'
    with runtime_state_lock:
        queue_state['pending'].discard(url)
        queue_state['active'].discard(url)
        queue_state[queue_terminal_state].add(url)
    upsert_crawl_record(
        url,
        state=terminal_state,
        status_code=status_code,
        content_type=content_type,
        error_kind=error_kind,
        error_message=error_message,
    )
    emit_queue_snapshot()


def note_content_type(raw_content_type):
    normalized = normalize_content_type(raw_content_type or '')
    bucket = normalized or 'unknown'
    content_types[bucket] = int(content_types.get(bucket, 0) or 0) + 1


def record_artifact(url, discovered_on=None, source_kind='link', note=None):
    record_artifact_discovery(artifact_genealogy, url, discovered_on, source_kind, note)


def mark_scope(url, discovered_on=None, source_kind='link'):
    normalized = normalize_url(url, base_url=main_url)
    if not normalized:
        return ''
    if is_in_scope(normalized, host, domain, scope_mode, scope_allow, scope_deny):
        internal.add(normalized)
        note_pending_url(normalized, discovered_on, source_kind)
    else:
        external.add(normalized)
    return normalized


extractor_context = {
    'processed': processed,
    'files': files,
    'forms': forms,
    'custom': custom,
    'keys': keys,
    'document_metadata': document_metadata,
    'document_leaks': document_leaks,
    'js_intel': js_intel,
    'threads': threads,
    'locations': locations,
    'stories': stories,
    'hidden_paths': hidden_paths,
    'scam_signals': scam_signals,
    'temporal_diffs': temporal_diffs,
    'bad_scripts': bad_scripts,
    'bad_intel': bad_intel,
    'endpoints': endpoints,
    'mark_scope': mark_scope,
    'host': host,
    'domain': domain,
    'scope_mode': scope_mode,
    'scope_allow': scope_allow,
    'scope_deny': scope_deny,
    'verbose': verbose,
    'verbose_prefix_internal': f'{crypt}Internal page: {{url}}',
    'verbose_prefix_external': f'{crypt}External page: {{url}}',
    'custom_regex': args.regex,
    'extract_secrets': api,
    'mode': mode,
    'record_artifact_discovery': record_artifact,
}

only_urls_context = dict(extractor_context, custom_regex=None, extract_secrets=False, bad_intel=set(), bad_scripts=set(), forms=set())


def checkpoint_payload(stage):
    return {
        'stage': stage,
        'specimen_input': target_input,
        'specimen_kind': specimen_kind,
        'specimen_profile': specimen_profile,
        'ritual_chain': ritual_chain,
        'preset': preset,
        'main_url': main_url,
        'host': host,
        'domain': domain,
        'scope_mode': scope_mode,
        'mode': mode,
        'output_dir': output_dir,
        'stats': stats.snapshot(visited=len(processed)),
        'content_types': content_types,
        'queue_state': {
            name: sorted(values)
            for name, values in queue_state.items()
        },
        'crawl_records': finalize_crawl_records(),
        'robots_metadata': {
            'rules': list(robots_metadata.get('rules') or []),
            'crawl_delay': robots_metadata.get('crawl_delay'),
        },
        'sitemap_metadata': {
            'sitemap_urls': list(sitemap_metadata.get('sitemap_urls') or []),
            'queued_urls': list(sitemap_metadata.get('queued_urls') or []),
        },
        'files': sorted(files),
        'forms': sorted(forms),
        'intel': sorted(intel),
        'robots': sorted(robots),
        'custom': sorted(custom),
        'failed': sorted(failed),
        'skipped': sorted(skipped),
        'redirects': sorted(redirects),
        'internal': sorted(internal),
        'scripts': sorted(scripts),
        'external': sorted(external),
        'fuzzable': sorted(fuzzable),
        'endpoints': sorted(endpoints),
        'keys': sorted(keys),
        'document_metadata': sorted(document_metadata),
        'document_leaks': sorted(document_leaks),
        'js_intel': sorted(js_intel),
        'threads': sorted(threads),
        'locations': sorted(locations),
        'stories': sorted(stories),
        'hidden_paths': sorted(hidden_paths),
        'scam_signals': sorted(scam_signals),
        'temporal_diffs': sorted(temporal_diffs),
        'site_anatomy': sorted(site_anatomy),
        'mutation_probes': sorted(mutation_probes),
        'artifact_genealogy': finalize_genealogy(artifact_genealogy),
        'processed': sorted(processed),
        'bad_scripts': sorted(bad_scripts),
        'bad_intel': [
            [list(match) if isinstance(match, tuple) else match, intel_name, url]
            for match, intel_name, url in sorted(
                bad_intel,
                key=lambda item: (str(item[1]), str(item[2]), str(item[0])),
            )
        ],
    }


def write_checkpoint(stage):
    if checkpoint_path:
        save_checkpoint(checkpoint_path, checkpoint_payload(stage))


def record_request_outcome(url, result, purpose):
    note_content_type(result.content_type)
    upsert_crawl_record(
        url,
        status_code=result.status_code,
        content_type=result.content_type,
        error_kind=result.error_kind,
        error_message=result.error_message,
    )
    if result.redirected:
        trail = ' -> '.join(
            normalize_url(hop, base_url=main_url) or hop
            for hop in [*result.redirect_chain, result.final_url]
        )
        redirects.add(f'{url} => {trail}')
        if url in artifact_genealogy:
            update_artifact_observation(
                artifact_genealogy,
                url,
                redirects=[normalize_url(hop, base_url=main_url) or hop for hop in [*result.redirect_chain, result.final_url]],
            )
    normalized_final = normalize_url(result.final_url, base_url=main_url)
    if normalized_final and normalized_final != url:
        mark_scope(normalized_final, url, 'redirect-target')
        if url in artifact_genealogy:
            record_artifact(normalized_final, url, 'redirect-target', 'redirect resolution')

    if result.skip_reason:
        skipped.add(f'{purpose}:{url}:{result.skip_reason}')
        finalize_url_state(
            url,
            'skipped',
            status_code=result.status_code,
            content_type=result.content_type,
            error_kind=result.error_kind or result.skip_reason,
            error_message=result.error_message or result.skip_reason.replace('-', ' '),
        )
        if result.error_kind:
            emit_webui_event('error', {
                'url': url,
                'category': result.error_kind,
                'message': result.error_message or result.skip_reason.replace('-', ' '),
                'status_code': result.status_code,
            })
        return False

    if result.ok:
        if purpose == 'page':
            if should_extract_markup(result.content_type):
                stats.bump('markup_pages')
            else:
                stats.bump('skipped')
                skipped.add(f'{purpose}:{url}:content-type:{result.content_type or "unknown"}')
                finalize_url_state(
                    url,
                    'skipped',
                    status_code=result.status_code,
                    content_type=result.content_type,
                    error_kind='unsupported-content-type',
                    error_message=f'Unsupported content type: {result.content_type or "unknown"}.',
                )
                emit_webui_event('error', {
                    'url': url,
                    'category': 'unsupported-content-type',
                    'message': f'Unsupported content type: {result.content_type or "unknown"}.',
                    'status_code': result.status_code,
                })
                return False
        elif purpose == 'script':
            if should_extract_script(result.content_type):
                stats.bump('script_pages')
            else:
                stats.bump('skipped')
                skipped.add(f'{purpose}:{url}:content-type:{result.content_type or "unknown"}')
                finalize_url_state(
                    url,
                    'skipped',
                    status_code=result.status_code,
                    content_type=result.content_type,
                    error_kind='unsupported-content-type',
                    error_message=f'Unsupported content type: {result.content_type or "unknown"}.',
                )
                emit_webui_event('error', {
                    'url': url,
                    'category': 'unsupported-content-type',
                    'message': f'Unsupported content type: {result.content_type or "unknown"}.',
                    'status_code': result.status_code,
                })
                return False
        finalize_url_state(
            url,
            'completed',
            status_code=result.status_code,
            content_type=result.content_type,
        )
    else:
        finalize_url_state(
            url,
            'failed',
            status_code=result.status_code,
            content_type=result.content_type,
            error_kind=result.error_kind or result.error,
            error_message=result.error_message or result.error or 'Request failed.',
        )
        emit_webui_event('error', {
            'url': url,
            'category': result.error_kind or result.error or 'request-error',
            'message': result.error_message or result.error or 'Request failed.',
            'status_code': result.status_code,
        })

    return result.ok


def maybe_render_page(url, result):
    if not args.render_js:
        return result.text
    with render_lock:
        if render_state['disabled']:
            return result.text
    try:
        rendered = render_page(
            result.final_url or url,
            timeout=args.render_timeout,
            headers=headers,
            cookie=cook,
            user_agent=random.choice(user_agents) if user_agents else None,
        )
    except Exception as exc:
        with render_lock:
            if not render_state['disabled']:
                render_state['disabled'] = True
                render_state['message'] = str(exc)
                print(f'{coffin}JS rendering disabled: {exc}')
        return result.text
    for discovered_url in rendered.urls:
        mark_scope(discovered_url, url, 'rendered-link')
    return rendered.html or result.text


def extractor(url):
    mark_active_url(url)
    result = requester(
        url, main_url, delay, cook, headers, timeout,
        host, proxies, user_agents, failed, processed, stats, policy=policy,
    )
    if not record_request_outcome(url, result, 'page'):
        return
    response = maybe_render_page(url, result)
    if only_urls:
        run_page_extractors(url, response, only_urls_context)
        return
    run_page_extractors(url, response, extractor_context)



def jscanner(url):
    mark_active_url(url)
    result = requester(
        url, main_url, delay, cook, headers, timeout,
        host, proxies, user_agents, failed, processed, stats, policy=policy,
    )
    if not record_request_outcome(url, result, 'script'):
        return
    update_artifact_observation(
        artifact_genealogy,
        url,
        content_type=result.content_type,
        body=result.text.encode('utf-8', 'ignore'),
        seen_label='current-run',
    )
    run_script_extractors(url, result.text, extractor_context)


def fetch_binary_document(url):
    proxy = random.choice(proxies) if proxies else None
    proxy_dict = proxy if proxy else None
    ua = random.choice(user_agents) if user_agents else 'Mozilla/5.0 (compatible; VampiricCrawler/1.0)'
    req_headers = {'User-Agent': ua}
    if cook:
        req_headers['Cookie'] = cook
    if headers:
        req_headers.update(headers)
    session = get_session()
    response = session.get(
        url,
        headers=req_headers,
        proxies=proxy_dict,
        timeout=timeout,
        verify=False,
        allow_redirects=True,
    )
    return response


def harvest_documents():
    document_urls = sorted(
        url for url in files
        if urlsplit(url).path.lower().endswith(tuple(DOCUMENT_EXTENSIONS))
    )
    if not document_urls:
        return
    print(f'{fang}Harvesting {len(document_urls)} document tomb{"s" if len(document_urls) != 1 else ""}…')
    for url in document_urls:
        mark_active_url(url)
        stats.bump('requests')
        try:
            response = fetch_binary_document(url)
        except Exception as exc:
            failed.add(url)
            stats.bump('failures')
            finalize_url_state(url, 'failed', error_kind='request-error', error_message=str(exc))
            emit_webui_event('error', {
                'url': url,
                'category': 'request-error',
                'message': str(exc),
                'status_code': None,
            })
            if verbose:
                print(f'{coffin}Could not exhume document {url}: {exc}')
            continue
        if response.history:
            stats.bump('redirects', len(response.history))
        if response.status_code >= 400:
            failed.add(url)
            stats.bump('failures')
            finalize_url_state(
                url,
                'failed',
                status_code=response.status_code,
                content_type=normalize_content_type(response.headers.get('Content-Type', '')),
                error_kind='blocked' if response.status_code in (401, 403, 429) else 'client-error',
                error_message='Request blocked by the target.' if response.status_code in (401, 403, 429) else f'Request failed with status {response.status_code}.',
            )
            continue
        stats.bump('successes')
        note_content_type(response.headers.get('Content-Type', ''))
        finalize_url_state(
            url,
            'completed',
            status_code=response.status_code,
            content_type=normalize_content_type(response.headers.get('Content-Type', '')),
        )
        metadata_records, leak_records = extract_document_records(
            response.url,
            response.content,
            normalize_content_type(response.headers.get('Content-Type', '')),
        )
        document_metadata.update(metadata_records)
        document_leaks.update(leak_records)
        update_artifact_observation(
            artifact_genealogy,
            url,
            content_type=normalize_content_type(response.headers.get('Content-Type', '')),
            body=response.content,
            title=next((item.split(' title=', 1)[1] for item in metadata_records if ' title=' in item), ''),
            metadata=sorted(metadata_records | leak_records),
            archive_presence=bool(args.archive),
            redirects=[hop.url for hop in response.history] + [response.url],
            seen_label='current-run',
        )


def discover_hidden_paths():
    if mode != 'hidden':
        return
    guesses = build_hidden_candidates(main_url, internal, scripts, endpoints)
    if not guesses:
        return
    print(f'{fang}Probing {len(guesses)} shadow path{"s" if len(guesses) != 1 else ""}…')
    for guess in guesses:
        normalized_guess = normalize_url(guess, base_url=main_url)
        if not normalized_guess:
            continue
        if normalized_guess in processed or normalized_guess in internal or normalized_guess in external:
            continue
        if not is_in_scope(normalized_guess, host, domain, scope_mode, scope_allow, scope_deny):
            continue
        note_pending_url(normalized_guess, main_url, 'hidden-probe')
        mark_active_url(normalized_guess)
        result = requester(
            normalized_guess, main_url, delay, cook, headers, timeout,
            host, proxies, user_agents, failed, processed, stats, policy=policy,
        )
        if not record_request_outcome(normalized_guess, result, 'page'):
            continue
        hidden_paths.add(normalized_guess)
        response = maybe_render_page(normalized_guess, result)
        run_page_extractors(normalized_guess, response, extractor_context)


def load_previous_snapshot(snapshot_dir):
    if not snapshot_dir or not os.path.isdir(snapshot_dir):
        return {}
    snapshot = {}
    for name in list(dataset_names) + ['stats']:
        path = os.path.join(snapshot_dir, f'{name}.txt')
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='utf-8') as handle:
            lines = [line.rstrip('\n') for line in handle if line.strip()]
        if name == 'stats':
            stats_dict = {}
            for line in lines:
                key, _, value = line.partition('=')
                if key:
                    stats_dict[key] = value
            snapshot[name] = stats_dict
        else:
            snapshot[name] = lines
    return snapshot


def snapshot_exists(snapshot_dir):
    if not snapshot_dir or not os.path.isdir(snapshot_dir):
        return False
    return any(
        os.path.exists(os.path.join(snapshot_dir, f'{name}.txt'))
        for name in list(dataset_names) + ['stats']
    )


def process_inline_specimen():
    inline_payload = specimen_profile.get('inline_payload') or ''
    if not inline_payload:
        return
    pseudo_url = main_url or 'https://inline.specimen.local/'
    internal.add(pseudo_url)
    processed.add(pseudo_url)
    upsert_crawl_record(pseudo_url, source_page='inline-specimen', source_kind='inline-html', depth=0, state='completed', content_type='text/html')
    with runtime_state_lock:
        queue_state['completed'].add(pseudo_url)
    stats.bump('markup_pages')
    note_content_type('text/html')
    run_page_extractors(pseudo_url, inline_payload, only_urls_context if only_urls else extractor_context)


def process_local_script_specimen():
    local_path = specimen_profile.get('local_path') or ''
    if not local_path:
        return
    script_url = f'file://{os.path.abspath(local_path)}'
    scripts.add(script_url)
    processed.add(script_url)
    upsert_crawl_record(script_url, source_page='local-file', source_kind='local-script', depth=0, state='active')
    record_artifact(script_url, 'local-file', 'local-script', 'local JS specimen')
    try:
        with open(local_path, 'r', encoding='utf-8') as handle:
            payload = handle.read()
    except OSError as exc:
        failed.add(script_url)
        stats.bump('failures')
        finalize_url_state(script_url, 'failed', error_kind='request-error', error_message=str(exc))
        print(f'{coffin}Could not read local script specimen: {exc}')
        return
    stats.bump('script_pages')
    note_content_type('application/javascript')
    finalize_url_state(script_url, 'completed', status_code=200, content_type='application/javascript')
    update_artifact_observation(
        artifact_genealogy,
        script_url,
        content_type='application/javascript',
        body=payload.encode('utf-8', 'ignore'),
        seen_label='current-run',
    )
    run_script_extractors(script_url, payload, extractor_context)


def process_local_document_specimen():
    local_path = specimen_profile.get('local_path') or ''
    if not local_path:
        return
    document_url = f'file://{os.path.abspath(local_path)}'
    files.add(document_url)
    processed.add(document_url)
    upsert_crawl_record(document_url, source_page='local-file', source_kind='local-document', depth=0, state='active')
    record_artifact(document_url, 'local-file', 'local-document', 'local PDF specimen')
    try:
        with open(local_path, 'rb') as handle:
            payload = handle.read()
    except OSError as exc:
        failed.add(document_url)
        stats.bump('failures')
        finalize_url_state(document_url, 'failed', error_kind='request-error', error_message=str(exc))
        print(f'{coffin}Could not read local document specimen: {exc}')
        return
    note_content_type('application/pdf')
    finalize_url_state(document_url, 'completed', status_code=200, content_type='application/pdf')
    metadata_records, leak_records = extract_document_records(document_url, payload, 'application/pdf')
    document_metadata.update(metadata_records)
    document_leaks.update(leak_records)
    update_artifact_observation(
        artifact_genealogy,
        document_url,
        content_type='application/pdf',
        body=payload,
        title=next((item.split(' title=', 1)[1] for item in metadata_records if ' title=' in item), ''),
        metadata=sorted(metadata_records | leak_records),
        archive_presence=False,
        seen_label='current-run',
    )


print(f'{fang}Target locked: {bold}{main_url}{end}')
print(f'{fang}Specimen       {specimen_profile.get("type")} ({specimen_profile.get("source")})')
print(f'{fang}Ritual chain   {ritual_chain}')
print(f'{fang}Preset         {preset}')
if resume_state:
    print(f'{fang}Rising from checkpoint: {bold}{args.resume}{end}')
print(f'{fang}The hunt begins… depth={crawl_level}, threads={thread_count}, delay={delay}s, scope={scope_mode}, mode={mode}')
if document_depth_forced:
    print(f'{crypt}Document harvester raised crawl depth to 1 so it can reach linked document tombs.')
print(f'{dark_red}{"─" * 60}{end}')
then = time.time()

if not resume_state:
    metadata = {'crawl_delay': None}
    if main_url:
        metadata = zap(main_url, args.archive, domain, host, internal, robots, proxies, headers)
        robots_metadata['rules'] = list(metadata.get('robots_rules') or [])
        robots_metadata['crawl_delay'] = metadata.get('crawl_delay')
        sitemap_metadata['sitemap_urls'] = list(metadata.get('sitemap_urls') or [])
        sitemap_metadata['queued_urls'] = list(metadata.get('sitemap_queued_urls') or [])
        emit_webui_event('robots', robots_metadata)
        emit_webui_event('sitemap', sitemap_metadata)
        if args.respect_robots_delay and metadata.get('crawl_delay') is not None:
            policy.update_robots_delay(metadata['crawl_delay'])
    seeded = set()
    extra_ritual_seeds = [seed for seed in ritual_plan.get('seed_urls', []) if seed and seed != main_url]
    for seed in list(internal) + extra_ritual_seeds + args.seeds + ([main_url] if main_url else []):
        normalized_seed = normalize_url(seed, base_url=main_url)
        if not normalized_seed:
            continue
        if is_in_scope(normalized_seed, host, domain, scope_mode, scope_allow, scope_deny):
            seeded.add(normalized_seed)
            note_pending_url(normalized_seed, 'seed', 'seed')
        else:
            external.add(normalized_seed)
    internal.clear()
    internal.update(remove_regex(seeded, args.exclude))
    if direct_remote_js:
        direct_script_url = specimen_profile['crawl_roots'][0]
        scripts.add(direct_script_url)
        note_pending_url(direct_script_url, main_url or direct_script_url, 'direct-script-specimen')
        record_artifact(direct_script_url, main_url or direct_script_url, 'direct-script-specimen', 'remote JS specimen')
    if direct_remote_pdf:
        direct_document_url = specimen_profile['crawl_roots'][0]
        files.add(direct_document_url)
        note_pending_url(direct_document_url, main_url or direct_document_url, 'direct-document-specimen')
        record_artifact(direct_document_url, main_url or direct_document_url, 'direct-document-specimen', 'remote PDF specimen')
    if direct_local_html:
        process_inline_specimen()
    if direct_local_js:
        process_local_script_specimen()
    if direct_local_pdf:
        process_local_document_specimen()
    write_checkpoint('seeded')
elif args.respect_robots_delay:
    metadata = zap(main_url, False, domain, host, set(), set(), proxies, headers)
    robots_metadata['rules'] = list(metadata.get('robots_rules') or [])
    robots_metadata['crawl_delay'] = metadata.get('crawl_delay')
    sitemap_metadata['sitemap_urls'] = list(metadata.get('sitemap_urls') or [])
    sitemap_metadata['queued_urls'] = list(metadata.get('sitemap_queued_urls') or [])
    emit_webui_event('robots', robots_metadata)
    emit_webui_event('sitemap', sitemap_metadata)
    if metadata.get('crawl_delay') is not None:
        policy.update_robots_delay(metadata['crawl_delay'])

for level in range(crawl_level):
    links = remove_regex(internal - processed, args.exclude)
    if not links:
        break
    if len(internal) <= len(processed) and len(internal) > 2 + len(args.seeds):
        break
    for link in links:
        upsert_crawl_record(link, depth=level + 1)
    print(f'{fang}🦇 Descending to depth {level + 1} — {len(links)} URL{"s" if len(links) != 1 else ""} to drain…')
    try:
        flash(extractor, links, thread_count)
    except KeyboardInterrupt:
        print(f'\n{moon}The vampire retreats into the darkness…')
        write_checkpoint(f'interrupted-depth-{level + 1}')
        break
    write_checkpoint(f'depth-{level + 1}')

if not only_urls:
    for src in bad_scripts:
        normalized_script = normalize_url(src, base_url=main_url)
        if not normalized_script:
            continue
        if is_in_scope(normalized_script, host, domain, scope_mode, scope_allow, scope_deny):
            scripts.add(normalized_script)
            note_pending_url(normalized_script, main_url, 'script-queue')
            record_artifact(normalized_script, main_url, 'script-queue', 'queued for js archaeology')
        else:
            external.add(normalized_script)

    if scripts and mode != 'document':
        print(f'{fang}Draining {len(scripts)} JavaScript script{"s" if len(scripts) != 1 else ""}…')
        flash(jscanner, scripts, thread_count)
        write_checkpoint('scripts-scanned')
    elif scripts and mode == 'document':
        print(f'{crypt}Document harvester mode skips JavaScript analysis so it can focus on document extraction.')

    for url in internal:
        fuzzable_url = normalize_fuzzable_url(url)
        if fuzzable_url:
            fuzzable.add(fuzzable_url)

    for match, intel_name, url in bad_intel:
        if isinstance(match, tuple):
            for item in match:
                if item:
                    if intel_name == 'CREDIT_CARD' and not luhn(item):
                        continue
                    intel.add(f'{intel_name}:{item}')
        else:
            if intel_name == 'CREDIT_CARD' and not luhn(match):
                continue
            intel.add(f'{url}:{intel_name}:{match}')

    for url in external:
        try:
            if top_level(url, fix_protocol=True) in INTELS:
                intel.add(url)
        except Exception:
            pass

    if mode == 'document':
        harvest_documents()
    if mode == 'hidden':
        discover_hidden_paths()

now = time.time()
diff = now - then
minutes, seconds, _ = timer(diff, processed)

os.makedirs(output_dir, exist_ok=True)
previous_snapshot = {}
if mode == 'temporal':
    baseline_dir = temporal_baseline
    if baseline_dir and snapshot_exists(baseline_dir):
        previous_snapshot = load_previous_snapshot(baseline_dir)
    elif snapshot_exists(output_dir):
        previous_snapshot = load_previous_snapshot(output_dir)
artifact_genealogy_placeholder = set()
datasets = [
    files, forms, intel, robots, custom, failed, skipped, redirects, internal, scripts, external, fuzzable, endpoints, keys,
    document_metadata, document_leaks, js_intel, threads, locations, stories, hidden_paths, scam_signals, temporal_diffs,
    site_anatomy, mutation_probes, artifact_genealogy_placeholder,
]
if mode == 'temporal' and previous_snapshot:
    current_snapshot = {
        name: sorted(dataset)
        for name, dataset in zip(dataset_names, datasets)
    }
    current_snapshot['stats'] = stats.snapshot(visited=len(processed))
    temporal_diffs.update(build_temporal_diffs(previous_snapshot, current_snapshot))
elif mode == 'temporal':
    temporal_diffs.add('dataset=temporal_diffs change=baseline-missing value=No prior snapshot found')

datasets_dict = {
    'files': sorted(files),
    'forms': sorted(forms),
    'intel': sorted(intel),
    'robots': sorted(robots),
    'custom': sorted(custom),
    'failed': sorted(failed),
    'skipped': sorted(skipped),
    'redirects': sorted(redirects),
    'internal': sorted(internal),
    'scripts': sorted(scripts),
    'external': sorted(external),
    'fuzzable': sorted(fuzzable),
    'endpoints': sorted(endpoints),
    'keys': sorted(keys),
    'document_metadata': sorted(document_metadata),
    'document_leaks': sorted(document_leaks),
    'js_intel': sorted(js_intel),
    'threads': sorted(threads),
    'locations': sorted(locations),
    'stories': sorted(stories),
    'hidden_paths': sorted(hidden_paths),
    'scam_signals': sorted(scam_signals),
    'temporal_diffs': sorted(temporal_diffs),
}
site_anatomy_map = build_site_anatomy(main_url or 'https://inline.specimen.local/', datasets_dict, artifact_genealogy, specimen_profile)
site_anatomy.update(anatomy_lines(site_anatomy_map))
mutation_probe_records = build_mutation_probes(main_url or 'https://inline.specimen.local/', datasets_dict)
mutation_probes.update(mutation_lines(mutation_probe_records))
artifact_genealogy_lines = set(genealogy_lines(artifact_genealogy))

datasets = [
    files, forms, intel, robots, custom, failed, skipped, redirects, internal, scripts, external, fuzzable, endpoints, keys,
    document_metadata, document_leaks, js_intel, threads, locations, stories, hidden_paths, scam_signals, temporal_diffs,
    site_anatomy, mutation_probes, artifact_genealogy_lines,
]
writer(datasets, dataset_names, output_dir)

visited_count = len(processed)
stats_summary = stats.snapshot(visited=visited_count)
writer([[
    f'{name}={value}' for name, value in sorted(stats_summary.items())
]], ['stats'], output_dir)

datasets_dict['site_anatomy'] = sorted(site_anatomy)
datasets_dict['mutation_probes'] = sorted(mutation_probes)
datasets_dict['artifact_genealogy'] = sorted(artifact_genealogy_lines)
datasets_dict['stats'] = stats_summary

print(f'\n{dark_red}{"─" * 60}{end}')
print(f'{blood}Harvest summary{end}')
for dataset, name in zip(datasets, dataset_names):
    if dataset:
        print(f'{fang}{name.capitalize():<14} {len(dataset)}')
print(f'{dark_red}{"─" * 60}{end}')
top_content_types = sorted(content_types.items(), key=lambda item: (-item[1], item[0]))[:5]
print(f'{fang}Visited         {visited_count}')
print(f'{fang}Specimen        {specimen_profile.get("type")}')
print(f'{fang}Ritual chain    {ritual_chain}')
print(f'{fang}Preset          {preset}')
print(f'{fang}Time elapsed    {minutes}m {seconds}s')
if diff > 0:
    print(f'{fang}Req/sec         {int(visited_count / diff)}')
print(f'{fang}Redirects       {stats_summary["redirects"]}')
print(f'{fang}Skipped         {stats_summary["skipped"]}')
print(f'{fang}Failures        {stats_summary["failures"]}')
print(f'{fang}Exported        {len(dataset_names) + 3}')
print(f'{fang}Top types       {", ".join(f"{name}:{count}" for name, count in top_content_types) or "-"}')

if args.dns:
    print(f'{fang}Seeking bloodlines (subdomains)…')
    try:
        import socket
        common = ['www', 'mail', 'ftp', 'smtp', 'pop', 'ns1', 'ns2', 'blog', 'dev', 'api', 'static', 'cdn', 'media', 'shop', 'secure', 'vpn', 'admin', 'portal', 'app', 'test']
        subdomains = set()
        for sub in common:
            candidate = f'{sub}.{domain}'
            try:
                socket.gethostbyname(candidate)
                subdomains.add(candidate)
                verb(f'Subdomain: {candidate}')
            except socket.gaierror:
                pass
        if subdomains:
            print(f'{blood}Found {len(subdomains)} bloodline(s)')
            writer([subdomains], ['subdomains'], output_dir)
            datasets_dict['subdomains'] = sorted(subdomains)
    except Exception as exc:
        print(f'{coffin}Subdomain enumeration failed: {exc}')

if args.export:
    from plugins.exporter import exporter
    exporter(output_dir, args.export, datasets_dict)

autopsy = build_autopsy(
    specimen=specimen_profile,
    ritual=ritual_plan,
    preset=preset,
    mode=mode,
    datasets=datasets_dict,
    stats=stats_summary,
    genealogy=artifact_genealogy,
    anatomy=site_anatomy_map,
    mutation_probes=mutation_probe_records,
    exports=['autopsy.json', 'autopsy.md', 'stats.txt', *([f'results.{args.export}'] if args.export else [])],
    duration_seconds=diff,
    content_types=content_types,
)
autopsy_json_path, autopsy_md_path = write_autopsy_files(output_dir, autopsy)
print(f'{fang}Autopsy JSON    {autopsy_json_path}')
print(f'{fang}Autopsy MD      {autopsy_md_path}')

write_checkpoint('complete')
print(f'\n{blood}The harvest is complete. Loot interred in {bold}{green}{output_dir}{end}')

if args.std and args.std in datasets_dict:
    selected = datasets_dict[args.std]
    if isinstance(selected, dict):
        for name, value in sorted(selected.items()):
            sys.stdout.write(f'{name}={value}\n')
    else:
        for item in selected:
            sys.stdout.write(str(item) + '\n')
