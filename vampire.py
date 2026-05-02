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
import re
import sys
import time
import warnings
import random

# Silence SSL warnings — creatures of the night care not for certificates
warnings.filterwarnings('ignore')

# ── Pretty colours & symbols ────────────────────────────────────────────────
from core.colors import (
    blood, fang, coffin, crypt, moon,
    red, dark_red, purple, green, white, end, bold,
)

# ── Vampire banner ───────────────────────────────────────────────────────────
BANNER = f"""
{dark_red}      .  *  .     .   *  . *  .   .  *  .     .   *
  *  .  ,      .        *      .   *   .      .   *  .
    .     ██╗   ██╗ █████╗ ███╗   ███╗██████╗{end}
{dark_red}  .  *   ██║   ██║██╔══██╗████╗ ████║██╔══██╗{end}      {purple}🦇{end}
{dark_red}         ╚██╗ ██╔╝███████║██╔████╔██║██████╔╝{end}
{dark_red}      *   ╚████╔╝ ██║  ██║██║╚██╔╝██║██╔═══╝{end}   {purple}🦇{end}
{dark_red}  .        ╚═══╝  ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝{end}
{dark_red}  ██████╗██████╗  █████╗ ██╗    ██╗██╗     ███████╗██████╗{end}
{dark_red} ██╔════╝██╔══██╗██╔══██╗██║    ██║██║     ██╔════╝██╔══██╗{end}
{dark_red} ██║     ██████╔╝███████║██║ █╗ ██║██║     █████╗  ██████╔╝{end}
{dark_red} ██║     ██╔══██╗██╔══██║██║███╗██║██║     ██╔══╝  ██╔══██╗{end}
{dark_red} ╚██████╗██║  ██║██║  ██║╚███╔███╔╝███████╗███████╗██║  ██║{end}
{dark_red}  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚══╝╚══╝ ╚══════╝╚══════╝╚═╝  ╚═╝{end}
{purple}             ☽  The Gothic Web Stalker  ☾{end}          {dark_red}v1.0.0{end}
"""
print(BANNER)

# ── Python version guard ─────────────────────────────────────────────────────
if sys.version_info < (3, 6):
    print(f'{coffin}Vampiric Crawler requires Python 3.6+. '
          f'Your mortal Python is too old.')
    sys.exit(1)

from urllib.parse import urlparse

import requests

import core.config
from core.config import INTELS
from core.flash import flash
from core.requester import requester
from core.utils import (
    luhn, proxy_type, is_good_proxy, top_level,
    extract_headers, verb, is_link, entropy,
    regxy, remove_regex, remove_file, timer, writer,
)
from core.regex import rintels, rendpoint, rhref, rscript, rentropy
from core.zap import zap

# ── CLI arguments ─────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(
    description='Vampiric Crawler — a gothic OSINT web spider',
    formatter_class=argparse.RawDescriptionHelpFormatter,
)

# Required
parser.add_argument('-u', '--url',
                    help='Target URL (the prey)', dest='root', required=False)

# Crawl controls
parser.add_argument('-l', '--level',
                    help='Depth of the hunt (default: 2)', dest='level',
                    type=int, default=2)
parser.add_argument('-t', '--threads',
                    help='Number of simultaneous fangs (default: 4)',
                    dest='threads', type=int, default=4)
parser.add_argument('-d', '--delay',
                    help='Delay between feedings in seconds (default: 0)',
                    dest='delay', type=float, default=0)
parser.add_argument('--timeout',
                    help='HTTP request timeout in seconds (default: 8)',
                    dest='timeout', type=float, default=8)

# Filters & seeds
parser.add_argument('-s', '--seeds',
                    help='Additional seed URLs to begin the hunt',
                    dest='seeds', nargs='+', default=[])
parser.add_argument('-r', '--regex',
                    help='Custom regex pattern to extract from pages',
                    dest='regex')
parser.add_argument('--exclude',
                    help='Exclude URLs matching this regex pattern',
                    dest='exclude')

# Output
parser.add_argument('-o', '--output',
                    help='Output directory for the harvested blood (loot)',
                    dest='output')
parser.add_argument('-e', '--export',
                    help='Also export results as this format',
                    dest='export', choices=['csv', 'json'])
parser.add_argument('--stdout',
                    help='Print a specific dataset to stdout (e.g. internal)',
                    dest='std')

# Auth / network
parser.add_argument('-c', '--cookie',
                    help='Cookie header value', dest='cook')
parser.add_argument('--user-agent',
                    help='Custom user agent string(s), comma-separated',
                    dest='user_agent')
parser.add_argument('-p', '--proxy',
                    help='Proxy or proxies in HOST:PORT format (comma-separated)',
                    dest='proxies', type=proxy_type)

# Feature switches
parser.add_argument('--keys',
                    help='Extract high-entropy strings (API keys, tokens)',
                    dest='api', action='store_true')
parser.add_argument('--dns',
                    help='Enumerate subdomains and dump DNS data',
                    dest='dns', action='store_true')
parser.add_argument('--wayback',
                    help='Fetch archived URLs from archive.org as extra seeds',
                    dest='archive', action='store_true')
parser.add_argument('--only-urls',
                    help='Only harvest URLs, skip intel extraction',
                    dest='only_urls', action='store_true')
parser.add_argument('-v', '--verbose',
                    help='Show every drop of blood (verbose output)',
                    dest='verbose', action='store_true')

args = parser.parse_args()

# ── Target URL sanity check ────────────────────────────────────────────────────
if not args.root:
    print(f'\n{coffin}No prey specified. Use {bold}-u <URL>{end} to choose a target.\n')
    parser.print_help()
    sys.exit(1)

main_inp = args.root.rstrip('/')

# ── Apply settings ─────────────────────────────────────────────────────────────
core.config.verbose = args.verbose

verbose      = args.verbose
delay        = args.delay
timeout      = args.timeout
cook         = args.cook or None
api          = bool(args.api)
only_urls    = bool(args.only_urls)
crawl_level  = args.level
thread_count = args.threads

# ── Proxy setup ────────────────────────────────────────────────────────────────
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

# ── Resolve URL scheme ─────────────────────────────────────────────────────────
if main_inp.startswith('http'):
    main_url = main_inp
else:
    try:
        requests.get('https://' + main_inp, proxies=random.choice(proxies),
                     timeout=timeout, verify=False)
        main_url = 'https://' + main_inp
    except Exception:
        main_url = 'http://' + main_inp

schema = main_url.split('//')[0]
host   = urlparse(main_url).netloc

try:
    domain = top_level(main_url)
except Exception:
    domain = host

output_dir = args.output or host

# ── User agents ─────────────────────────────────────────────────────────────────
if args.user_agent:
    user_agents = [ua.strip() for ua in args.user_agent.split(',')]
else:
    ua_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'core', 'user-agents.txt')
    try:
        with open(ua_file, 'r') as f:
            user_agents = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        user_agents = ['Mozilla/5.0 (compatible; VampiricCrawler/1.0)']

# ── Data stores ───────────────────────────────────────────────────────────────
keys      = set()            # High-entropy secret keys
files     = set()            # Static assets (pdf, png, …)
intel     = set()            # Emails, social accounts, buckets, …
robots    = set()            # robots.txt entries
custom    = set()            # Custom regex matches
failed    = set()            # URLs that could not be fetched
scripts   = set()            # JavaScript files
external  = set()            # Out-of-scope URLs
fuzzable  = set()            # URLs with query parameters
endpoints = set()            # JS-extracted API endpoints
processed = {'dummy'}        # Already-visited URLs
internal  = set(args.seeds)  # In-scope URLs queue

bad_scripts = set()
bad_intel   = set()

suppress_regex = False

# ── Core extraction functions ──────────────────────────────────────────────────

def intel_extractor(url, response):
    """Sift through the victim's response for secrets."""
    for name, pattern in rintels:
        # Strip scripts and tags for cleaner text intel
        res = re.sub(r'<(script).*?</\1>(?s)', '', response)
        res = re.sub(r'<[^<]+?>', '', res)
        for match in pattern.findall(res):
            verb('Intel', match)
            bad_intel.add((match, name, url))


def js_extractor(response):
    """Extract JavaScript file references from the response."""
    for match in rscript.findall(response):
        src = match[2].replace("'", '').replace('"', '')
        verb('JS file', src)
        bad_scripts.add(src)


def extractor(url):
    """Feed on *url*: request it and harvest every link and secret."""
    response = requester(
        url, main_url, delay, cook, {}, timeout,
        host, proxies, user_agents, failed, processed,
    )

    # Harvest links
    for link_match in rhref.findall(response):
        link = link_match[2].replace("'", '').replace('"', '').split('#')[0]
        if not is_link(link, processed, files):
            continue
        if link.startswith('http'):
            if link.startswith(main_url):
                verb('Internal page', link)
                internal.add(link)
            else:
                verb('External page', link)
                external.add(link)
        elif link.startswith('//'):
            if link.split('/')[2].startswith(host):
                verb('Internal page', link)
                internal.add(f'{schema}:{link}')
            else:
                verb('External page', link)
                external.add(link)
        elif link.startswith('/'):
            verb('Internal page', link)
            internal.add(main_url.rstrip('/') + link)
        else:
            base = remove_file(url)
            full = (base + '/' + link) if not base.endswith('/') else (base + link)
            verb('Internal page', full)
            internal.add(full)

    if not only_urls:
        intel_extractor(url, response)
        js_extractor(response)

    if args.regex and not suppress_regex:
        regxy(args.regex, response, suppress_regex, custom)

    if api:
        for match in rentropy.findall(response):
            if entropy(match) >= 4:
                verb('Key', match)
                keys.add(f'{url}: {match}')


def jscanner(url):
    """Drain JavaScript files for endpoint paths."""
    response = requester(
        url, main_url, delay, cook, {}, timeout,
        host, proxies, user_agents, failed, processed,
    )
    for match in rendpoint.findall(response):
        path = match if isinstance(match, str) else (match[0] or match[1])
        if path and not re.search(r'[}{><"\']', path) and path != '/':
            verb('JS endpoint', path)
            endpoints.add(path)


# ── Begin the hunt ─────────────────────────────────────────────────────────────
print(f'{fang}Target locked: {bold}{main_url}{end}')
print(f'{fang}The hunt begins… '
      f'depth={crawl_level}, threads={thread_count}, delay={delay}s')
print(f'{dark_red}{"─" * 60}{end}')

then = time.time()

# Seed from robots.txt, sitemap.xml (and optionally Wayback Machine)
zap(main_url, args.archive, domain, host, internal, robots, proxies)
internal.add(main_url)

internal = set(remove_regex(internal, args.exclude))

# ── Recursive crawl ────────────────────────────────────────────────────────────
for level in range(crawl_level):
    links = remove_regex(internal - processed, args.exclude)
    if not links:
        break
    if len(internal) <= len(processed) and len(internal) > 2 + len(args.seeds):
        break
    print(f'{fang}🦇 Descending to depth {level + 1} — '
          f'{len(links)} URL{"s" if len(links) != 1 else ""} to drain…')
    try:
        flash(extractor, links, thread_count)
    except KeyboardInterrupt:
        print(f'\n{moon}The vampire retreats into the darkness…')
        break

# ── Scan JavaScript files ──────────────────────────────────────────────────────
if not only_urls:
    for src in bad_scripts:
        if src.startswith(main_url):
            scripts.add(src)
        elif src.startswith('/') and not src.startswith('//'):
            scripts.add(main_url.rstrip('/') + src)
        elif not src.startswith('http') and not src.startswith('//'):
            scripts.add(main_url.rstrip('/') + '/' + src)

    if scripts:
        print(f'{fang}Draining {len(scripts)} JavaScript script'
              f'{"s" if len(scripts) != 1 else ""}…')
        flash(jscanner, scripts, thread_count)

    # Build fuzzable URLs
    for url in internal:
        if '=' in url:
            fuzzable.add(url)

    # Finalise intel
    for match, intel_name, url in bad_intel:
        if isinstance(match, tuple):
            for x in match:
                if x:
                    if intel_name == 'CREDIT_CARD' and not luhn(x):
                        continue
                    intel.add(f'{intel_name}:{x}')
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

# ── Record time ────────────────────────────────────────────────────────────────
now  = time.time()
diff = now - then
minutes, seconds, _ = timer(diff, processed)

# ── Save results ───────────────────────────────────────────────────────────────
os.makedirs(output_dir, exist_ok=True)

datasets      = [files, intel, robots, custom, failed, internal,
                 scripts, external, fuzzable, endpoints, keys]
dataset_names = ['files', 'intel', 'robots', 'custom', 'failed', 'internal',
                 'scripts', 'external', 'fuzzable', 'endpoints', 'keys']

writer(datasets, dataset_names, output_dir)

# ── Print summary ──────────────────────────────────────────────────────────────
print(f'\n{dark_red}{"─" * 60}{end}')
for dataset, name in zip(datasets, dataset_names):
    if dataset:
        print(f'{blood}{name.capitalize()}: {len(dataset)}')
print(f'{dark_red}{"─" * 60}{end}')
print(f'{fang}Total URLs visited : {len(processed) - 1}')
print(f'{fang}Time elapsed       : {minutes}m {seconds}s')
if diff > 0:
    print(f'{fang}Requests per second: {int((len(processed) - 1) / diff)}')

# ── Optional extras ────────────────────────────────────────────────────────────
datasets_dict = {
    'files':     list(files),    'intel':     list(intel),
    'robots':    list(robots),   'custom':    list(custom),
    'failed':    list(failed),   'internal':  list(internal),
    'scripts':   list(scripts),  'external':  list(external),
    'fuzzable':  list(fuzzable), 'endpoints': list(endpoints),
    'keys':      list(keys),
}

if args.dns:
    print(f'{fang}Seeking bloodlines (subdomains)…')
    try:
        import socket
        # Brute-force a small wordlist of common subdomains
        common = ['www', 'mail', 'ftp', 'smtp', 'pop', 'ns1', 'ns2',
                  'blog', 'dev', 'api', 'static', 'cdn', 'media', 'shop',
                  'secure', 'vpn', 'admin', 'portal', 'app', 'test']
        subdomains = set()
        for sub in common:
            candidate = f'{sub}.{domain}'
            try:
                socket.gethostbyname(candidate)
                subdomains.add(candidate)
                verb('Subdomain', candidate)
            except socket.gaierror:
                pass
        if subdomains:
            print(f'{blood}Found {len(subdomains)} bloodline(s)')
            writer([subdomains], ['subdomains'], output_dir)
            datasets_dict['subdomains'] = list(subdomains)
    except Exception as e:
        print(f'{coffin}Subdomain enumeration failed: {e}')

if args.export:
    from plugins.exporter import exporter
    exporter(output_dir, args.export, datasets_dict)

print(f'\n{blood}The harvest is complete. '
      f'Loot interred in {bold}{green}{output_dir}{end}')

if args.std and args.std in datasets_dict:
    for item in datasets_dict[args.std]:
        sys.stdout.write(str(item) + '\n')
