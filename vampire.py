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
import os
import random
import re
import sys
import threading
import time
import warnings
from urllib.parse import urlparse

warnings.filterwarnings('ignore')

from core.colors import (
    blood, fang, coffin, crypt, moon,
    dark_red, green, end, bold,
)
from core.checkpoint import load_checkpoint, normalize_checkpoint_sets, save_checkpoint
import core.config
from core.config import INTELS
from core.extractors import run_page_extractors, run_script_extractors
from core.flash import flash
from core.politeness import PolitenessController
from core.render import render_page
from core.requester import requester, get_session
from core.utils import (
    CrawlStats,
    extract_headers,
    is_in_scope,
    normalize_fuzzable_url,
    normalize_url,
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
parser.add_argument('--render-js', help='Render pages in headless Chromium before extraction', action='store_true')
parser.add_argument('--render-timeout', help='Per-page render timeout in seconds (default: 12)', type=float, default=12)
parser.add_argument('--checkpoint', help='Write crawl state to this checkpoint file')
parser.add_argument('--resume', help='Resume a previous crawl from this checkpoint file')
parser.add_argument('--respect-robots-delay', help='Honor robots.txt Crawl-delay when present', action='store_true')
parser.add_argument('--host-concurrency', help='Maximum concurrent requests per host (default: 2)', type=int, default=2)
parser.add_argument('--disable-adaptive-backoff', help='Disable automatic backoff on 429/503 responses', action='store_true')
parser.add_argument('-v', '--verbose', help='Show every drop of blood (verbose output)', dest='verbose', action='store_true')
args = parser.parse_args()

resume_state = None
if args.resume:
    try:
        resume_state = load_checkpoint(args.resume)
    except Exception as exc:
        print(f'{coffin}Could not resume from checkpoint: {exc}')
        sys.exit(1)
    if not args.root:
        args.root = resume_state.get('main_url')

if not args.root:
    print(f'\n{coffin}No prey specified. Use {bold}-u <URL>{end} to choose a target.\n')
    parser.print_help()
    sys.exit(1)

core.config.verbose = args.verbose
verbose = args.verbose
delay = args.delay
timeout = args.timeout
cook = args.cook or None
api = bool(args.api)
only_urls = bool(args.only_urls)
crawl_level = args.level
thread_count = args.threads
scope_mode = args.scope
checkpoint_path = args.checkpoint or args.resume


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

if resume_state:
    main_url = resume_state.get('main_url') or ''
    requested_root = normalize_url(args.root) if args.root else ''
    if requested_root and main_url and requested_root != main_url:
        print(f'{coffin}Checkpoint prey mismatch: {requested_root} != {main_url}')
        sys.exit(1)
else:
    main_inp = args.root.rstrip('/')
    if main_inp.startswith('http'):
        main_url = main_inp
    else:
        try:
            probe_proxy = random.choice(proxies) if proxies else None
            get_session().get('https://' + main_inp, proxies=probe_proxy, timeout=timeout, verify=False, headers=headers or None)
            main_url = 'https://' + main_inp
        except Exception:
            main_url = 'http://' + main_inp
    main_url = normalize_url(main_url)

if not main_url:
    print(f'{coffin}The chosen prey could not be normalized into a crawlable URL.')
    sys.exit(1)

host = urlparse(main_url).netloc
try:
    domain = top_level(main_url)
except Exception:
    domain = host
output_dir = args.output or (resume_state.get('output_dir') if resume_state else None) or host

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
processed = set()
bad_scripts = set()
bad_intel = set()
render_state = {'disabled': False, 'message': None}
render_lock = threading.Lock()

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
    processed.update(restored['processed'])
    bad_scripts.update(restored['bad_scripts'])
    bad_intel.update(restored['bad_intel'])
    stats = CrawlStats.from_snapshot(resume_state.get('stats'))

policy = PolitenessController(
    base_delay=delay,
    host_concurrency=args.host_concurrency,
    adaptive_backoff=not args.disable_adaptive_backoff,
)


def mark_scope(url):
    normalized = normalize_url(url, base_url=main_url)
    if not normalized:
        return ''
    if is_in_scope(normalized, host, domain, scope_mode, scope_allow, scope_deny):
        internal.add(normalized)
    else:
        external.add(normalized)
    return normalized


extractor_context = {
    'processed': processed,
    'files': files,
    'forms': forms,
    'custom': custom,
    'keys': keys,
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
}

only_urls_context = dict(extractor_context, custom_regex=None, extract_secrets=False, bad_intel=set(), bad_scripts=set(), forms=set())


def checkpoint_payload(stage):
    return {
        'stage': stage,
        'main_url': main_url,
        'host': host,
        'domain': domain,
        'scope_mode': scope_mode,
        'output_dir': output_dir,
        'stats': stats.snapshot(visited=len(processed)),
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
    if result.redirected:
        trail = ' -> '.join(
            normalize_url(hop, base_url=main_url) or hop
            for hop in [*result.redirect_chain, result.final_url]
        )
        redirects.add(f'{url} => {trail}')
    normalized_final = normalize_url(result.final_url, base_url=main_url)
    if normalized_final and normalized_final != url:
        mark_scope(normalized_final)

    if result.skip_reason:
        skipped.add(f'{purpose}:{url}:{result.skip_reason}')
        return False

    if result.ok:
        if purpose == 'page':
            if should_extract_markup(result.content_type):
                stats.bump('markup_pages')
            else:
                stats.bump('skipped')
                skipped.add(f'{purpose}:{url}:content-type:{result.content_type or "unknown"}')
                return False
        elif purpose == 'script':
            if should_extract_script(result.content_type):
                stats.bump('script_pages')
            else:
                stats.bump('skipped')
                skipped.add(f'{purpose}:{url}:content-type:{result.content_type or "unknown"}')
                return False

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
        mark_scope(discovered_url)
    return rendered.html or result.text


def extractor(url):
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
    result = requester(
        url, main_url, delay, cook, headers, timeout,
        host, proxies, user_agents, failed, processed, stats, policy=policy,
    )
    if not record_request_outcome(url, result, 'script'):
        return
    run_script_extractors(url, result.text, extractor_context)


print(f'{fang}Target locked: {bold}{main_url}{end}')
if resume_state:
    print(f'{fang}Rising from checkpoint: {bold}{args.resume}{end}')
print(f'{fang}The hunt begins… depth={crawl_level}, threads={thread_count}, delay={delay}s, scope={scope_mode}')
print(f'{dark_red}{"─" * 60}{end}')
then = time.time()

if not resume_state:
    metadata = zap(main_url, args.archive, domain, host, internal, robots, proxies, headers)
    if args.respect_robots_delay and metadata.get('crawl_delay') is not None:
        policy.update_robots_delay(metadata['crawl_delay'])
    seeded = set()
    for seed in list(internal) + args.seeds + [main_url]:
        normalized_seed = normalize_url(seed, base_url=main_url)
        if not normalized_seed:
            continue
        if is_in_scope(normalized_seed, host, domain, scope_mode, scope_allow, scope_deny):
            seeded.add(normalized_seed)
        else:
            external.add(normalized_seed)
    internal.clear()
    internal.update(remove_regex(seeded, args.exclude))
    write_checkpoint('seeded')
elif args.respect_robots_delay:
    metadata = zap(main_url, False, domain, host, set(), set(), proxies, headers)
    if metadata.get('crawl_delay') is not None:
        policy.update_robots_delay(metadata['crawl_delay'])

for level in range(crawl_level):
    links = remove_regex(internal - processed, args.exclude)
    if not links:
        break
    if len(internal) <= len(processed) and len(internal) > 2 + len(args.seeds):
        break
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
        else:
            external.add(normalized_script)

    if scripts:
        print(f'{fang}Draining {len(scripts)} JavaScript script{"s" if len(scripts) != 1 else ""}…')
        flash(jscanner, scripts, thread_count)
        write_checkpoint('scripts-scanned')

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

now = time.time()
diff = now - then
minutes, seconds, _ = timer(diff, processed)

os.makedirs(output_dir, exist_ok=True)
datasets = [files, forms, intel, robots, custom, failed, skipped, redirects, internal, scripts, external, fuzzable, endpoints, keys]
dataset_names = ['files', 'forms', 'intel', 'robots', 'custom', 'failed', 'skipped', 'redirects', 'internal', 'scripts', 'external', 'fuzzable', 'endpoints', 'keys']
writer(datasets, dataset_names, output_dir)

visited_count = len(processed)
stats_summary = stats.snapshot(visited=visited_count)
writer([[
    f'{name}={value}' for name, value in sorted(stats_summary.items())
]], ['stats'], output_dir)

print(f'\n{dark_red}{"─" * 60}{end}')
print(f'{blood}Harvest summary{end}')
for dataset, name in zip(datasets, dataset_names):
    if dataset:
        print(f'{fang}{name.capitalize():<14} {len(dataset)}')
print(f'{dark_red}{"─" * 60}{end}')
print(f'{fang}Visited         {visited_count}')
print(f'{fang}Time elapsed    {minutes}m {seconds}s')
if diff > 0:
    print(f'{fang}Req/sec         {int(visited_count / diff)}')
print(f'{fang}Redirects       {stats_summary["redirects"]}')
print(f'{fang}Skipped         {stats_summary["skipped"]}')
print(f'{fang}Failures        {stats_summary["failures"]}')

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
    'stats': stats_summary,
}

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
