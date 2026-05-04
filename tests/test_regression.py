import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from core import render, zap
from core.checkpoint import load_checkpoint, normalize_checkpoint_sets, save_checkpoint
from core.autopsy import build_site_anatomy
from core.modes import (
    build_hidden_candidates,
    build_temporal_diffs,
    coerce_preset,
    coerce_ritual_chain,
    extract_document_records,
    extract_js_intel,
    extract_location_records,
    extract_scam_signals,
    extract_story_records,
    extract_thread_records,
)
from core.specimen import classify_specimen, resolve_ritual_plan
from core.politeness import PolitenessController
from core.utils import (
    extract_headers,
    is_in_scope,
    normalize_fuzzable_url,
    normalize_url,
    top_level,
    writer,
)
from plugins.exporter import exporter
from webapp import CrawlRun, build_crawl_command, create_app

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class FixtureHandler(BaseHTTPRequestHandler):
    header_failures = []
    flaky_hits = 0

    def _send(self, status, body, content_type='text/html', headers=None):
        encoded = body if isinstance(body, bytes) else body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(encoded)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.headers.get('X-Blood') != 'moon':
            FixtureHandler.header_failures.append(self.path)

        base_url = self.server.base_url
        if self.path == '/':
            body = (
                '<html><body>'
                '<a href="/page">page</a>'
                '<a href="/redirect">redirect</a>'
                '<a href="/binary">binary</a>'
                '<a href="/dup?b=2&a=1">dup-a</a>'
                '<a href="/dup?a=1&b=2#frag">dup-b</a>'
                '<a href="./dup/?a=9&b=8">dup-c</a>'
                '<a href="/appdata">appdata</a>'
                '<a href="/thread">thread</a>'
                '<a href="/geo">geo</a>'
                '<a href="/news">news</a>'
                '<a href="/offer">offer</a>'
                '<a href="/report.pdf">report</a>'
                '<a href="https://discord.gg/nightshift">discord</a>'
                '<script src="/script.js"></script>'
                '<form action="/submit" method="post">'
                '<input name="email" type="email">'
                '<input name="token" type="hidden">'
                '</form>'
                '</body></html>'
            )
            self._send(200, body)
        elif self.path == '/page':
            body = (
                '<html><body>EMAIL:test@example.com '
                'ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN0123456789 '
                '<a href="/flaky">flaky</a></body></html>'
            )
            self._send(200, body)
        elif self.path == '/appdata':
            body = (
                '<html><body>'
                '<script type="application/json">'
                '{"api":"/api/discovered","graphql":"/graphql","swagger":"/openapi.json","manifest":"/manifest.json"}'
                '</script>'
                '</body></html>'
            )
            self._send(200, body)
        elif self.path.startswith('/dup'):
            self._send(200, '<html><body>duplicate</body></html>')
        elif self.path == '/landing':
            self._send(200, '<html><body>landed</body></html>')
        elif self.path == '/redirect':
            self._send(302, '', headers={'Location': base_url + '/landing'})
        elif self.path == '/binary':
            self._send(200, '%PDF-1.4', content_type='application/pdf')
        elif self.path == '/script.js':
            self._send(
                200,
                'const api="/api/crypt";'
                'fetch("/graphql");'
                'const betaCheckoutFlag=true;'
                'const runtimeConfig={"base":"/api/crypt","token":"sk_live_1234567890abcdef"};'
                'const routeName="/hidden/panel";'
                'const view="AdminView";'
                'const bucket="https://cdn.example-cdn.com/assets/app.js";'
                'const ga="G-ABC1234";'
                'const env=process.env.NEXT_PUBLIC_API_URL;'
                'console.error("ancient stack trace");'
                '// old admin route retired'
                '//# sourceMappingURL=/script.js.map',
                content_type='application/javascript',
            )
        elif self.path == '/script.js.map':
            self._send(200, '{"version":3}', content_type='application/json')
        elif self.path == '/api/discovered':
            self._send(200, '<html><body>api</body></html>', content_type='application/json')
        elif self.path == '/api/crypt':
            self._send(200, '{"ok":true}', content_type='application/json')
        elif self.path == '/graphql':
            self._send(200, '{"data":{}}', content_type='application/json')
        elif self.path == '/openapi.json':
            self._send(200, '{"openapi":"3.1.0"}', content_type='application/json')
        elif self.path == '/manifest.json':
            self._send(200, '{"name":"fixture"}', content_type='application/json')
        elif self.path == '/submit':
            self._send(200, '<html><body>submitted</body></html>')
        elif self.path == '/hidden':
            self._send(200, '<html><body>hidden chamber</body></html>')
        elif self.path == '/admin':
            self._send(200, '<html><body>admin reliquary</body></html>')
        elif self.path == '/thread':
            self._send(
                200,
                '<html><head><title>Night Thread</title></head><body>'
                '<article class="post" id="post-1"><span class="author">CountZero</span>'
                '<p>First omen rises.</p></article>'
                '<article class="reply" id="post-2" data-parent="post-1"><span class="username">deleted-user</span>'
                '<blockquote>First omen rises.</blockquote><p>Reply from the dark.</p></article>'
                '</body></html>',
            )
        elif self.path == '/geo':
            self._send(
                200,
                '<html lang="en"><head><meta name="geo.position" content="40.7128;-74.0060"></head>'
                '<body>Gathering in New York near Midnight Harbor 40.7128, -74.0060</body></html>',
            )
        elif self.path == '/news':
            self._send(
                200,
                '<html lang="en"><head>'
                '<title>Vampire bats swarm the wires</title>'
                '<meta property="og:site_name" content="Night Wire">'
                '<meta property="article:published_time" content="2026-05-03T00:15:00Z">'
                '</head><body>'
                '"Witnesses saw sparks in the abbey."'
                '<a href="https://mirror.example.net/story">mirror</a>'
                '</body></html>',
            )
        elif self.path == '/offer':
            self._send(
                200,
                '<html><body>Limited time! Only 2 left. Offer ends in 03:00. Crypto only.</body></html>',
            )
        elif self.path == '/report.pdf':
            self._send(
                200,
                b'%PDF-1.4\n1 0 obj<< /Author (Dracula) /Title (Night Ledger) >>endobj\n'
                b'Contact: archivist@example.com\nPath C:\\Users\\Vlad\\Documents\\ledger.xlsx\n',
                content_type='application/pdf',
            )
        elif self.path == '/sitemap-only':
            self._send(200, '<html><body>sitemap only</body></html>')
        elif self.path == '/sitemap-deep':
            self._send(200, '<html><body>sitemap deep</body></html>')
        elif self.path == '/flaky':
            FixtureHandler.flaky_hits += 1
            if FixtureHandler.flaky_hits < 3:
                self._send(500, 'try again', content_type='text/plain')
            else:
                self._send(200, '<html><body>stable now</body></html>')
        elif self.path == '/robots.txt':
            body = (
                'User-agent: OtherBot\n'
                'Disallow: /other-only\n\n'
                'User-agent: *\n'
                'Allow: /page\n'
                'Allow: /flaky\n'
                'Disallow: /hidden\n'
                'Crawl-delay: 1\n'
                'Sitemap: {}/sitemap.xml\n'.format(base_url)
            )
            self._send(200, body, content_type='text/plain')
        elif self.path == '/sitemap.xml':
            body = (
                '<sitemapindex>'
                '<sitemap><loc>{}/nested-sitemap.xml</loc></sitemap>'
                '<sitemap><loc>{}/loop-sitemap.xml</loc></sitemap>'
                '</sitemapindex>'
            ).format(base_url, base_url)
            self._send(200, body, content_type='application/xml')
        elif self.path == '/nested-sitemap.xml':
            body = (
                '<urlset>'
                '<url><loc>{}/redirect</loc></url>'
                '<url><loc>{}/sitemap-only</loc></url>'
                '</urlset>'
            ).format(base_url, base_url)
            self._send(200, body, content_type='application/xml')
        elif self.path == '/loop-sitemap.xml':
            body = (
                '<sitemapindex>'
                '<sitemap><loc>{}/sitemap.xml</loc></sitemap>'
                '<sitemap><loc>{}/deep-sitemap.xml</loc></sitemap>'
                '</sitemapindex>'
            ).format(base_url, base_url)
            self._send(200, body, content_type='application/xml')
        elif self.path == '/deep-sitemap.xml':
            body = '<urlset><url><loc>{}/sitemap-deep</loc></url></urlset>'.format(base_url)
            self._send(200, body, content_type='application/xml')
        else:
            self._send(404, 'missing', content_type='text/plain')

    def log_message(self, format, *args):
        return




class FakeResponse(object):
    def __init__(self, url):
        self.url = url

class FakePage(object):
    def __init__(self):
        self._callbacks = {}

    def on(self, name, callback):
        self._callbacks[name] = callback
        callback(FakeResponse('https://example.com/graphql'))

    def goto(self, url, wait_until='networkidle', timeout=0):
        return None

    def content(self):
        return '<html><body><a href="https://example.com/rendered-only">rendered</a></body></html>'

    def eval_on_selector_all(self, selector, script):
        return ['https://example.com/rendered-only']


class FakeContext(object):
    def __init__(self):
        self.cookies = []

    def add_cookies(self, cookies):
        self.cookies.extend(cookies)

    def new_page(self):
        return FakePage()

    def close(self):
        return None


class FakeBrowser(object):
    def new_context(self, **kwargs):
        return FakeContext()


class RegressionTests(unittest.TestCase):
    def _write_test_launcher(self, tmpdir):
        launcher_path = os.path.join(tmpdir, 'launch.sh')
        with open(os.path.join(REPO_ROOT, 'launch.sh'), 'r', encoding='utf-8') as src:
            launcher = src.read()
        with open(launcher_path, 'w', encoding='utf-8') as handle:
            handle.write(launcher)
        os.chmod(launcher_path, 0o755)
        return launcher_path

    def _write_python_stub(self, tmpdir, body):
        bin_dir = os.path.join(tmpdir, 'bin')
        os.makedirs(bin_dir)
        python_stub = os.path.join(bin_dir, 'python3')
        with open(python_stub, 'w', encoding='utf-8') as handle:
            handle.write(body)
        os.chmod(python_stub, 0o755)
        return bin_dir

    def _write_entrypoint_stub(self, tmpdir):
        app_path = os.path.join(tmpdir, 'vampire.py')
        with open(app_path, 'w', encoding='utf-8') as handle:
            handle.write('print("stub vampire")\n')
        return app_path

    def test_url_normalization_helpers(self):
        self.assertEqual(
            normalize_url('HTTPS://Example.com//a/../dup/?b=2&a=1#frag'),
            'https://example.com/dup?a=1&b=2',
        )
        self.assertEqual(
            normalize_fuzzable_url('https://example.com/dup?b=2&a=1&a=9'),
            'https://example.com/dup?a=&b=',
        )
        self.assertEqual(top_level('https://api.example.co.uk/path'), 'example.co.uk')
        self.assertTrue(is_in_scope('https://api.example.co.uk/path', 'www.example.co.uk', 'example.co.uk', 'domain'))
        self.assertFalse(is_in_scope('https://api.example.co.uk/path', 'www.example.co.uk', 'example.co.uk', 'host'))

    def test_specimen_classifier_and_ritual_plan(self):
        specimen = classify_specimen('https://web.archive.org/web/20240101000000/https://example.com/login')
        ritual = resolve_ritual_plan(specimen)
        self.assertEqual(specimen['type'], 'archived_url')
        self.assertEqual(specimen['crawl_roots'][0], 'https://example.com/login')
        self.assertEqual(ritual['ritual_chain'], 'dead_page_resurrection')
        self.assertEqual(coerce_ritual_chain(ritual['ritual_chain']), 'dead_page_resurrection')
        self.assertEqual(coerce_preset('quick'), 'quick')

    def test_extract_headers_requires_key_value_format(self):
        self.assertEqual(
            extract_headers('X-Test: one\nX-Night: eternal'),
            {'X-Test': 'one', 'X-Night': 'eternal'},
        )
        with self.assertRaises(ValueError):
            extract_headers('BadHeader')

    def test_exporter_writes_stats_dict_to_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter(tmpdir, 'csv', {'internal': ['https://example.com'], 'stats': {'visited': 1}})
            with open(os.path.join(tmpdir, 'results.csv'), 'r', encoding='utf-8') as handle:
                content = handle.read()
            self.assertIn('internal,https://example.com', content)
            self.assertIn('stats,visited=1', content)

    def test_writer_preserves_list_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            writer([['second', 'first', 'third']], ['ordered'], tmpdir)
            with open(os.path.join(tmpdir, 'ordered.txt'), 'r', encoding='utf-8') as handle:
                lines = handle.read().splitlines()
            self.assertEqual(lines, ['second', 'first', 'third'])

    def test_site_anatomy_splits_third_party_buckets(self):
        anatomy = build_site_anatomy(
            'https://example.com',
            {
                'internal': ['https://example.com/login'],
                'external': [
                    'https://www.googletagmanager.com/gtm.js',
                    'https://cdn.example.net/app.js',
                    'https://partner.example.org/readme',
                    'https://github.com/example/project',
                ],
                'files': [],
                'endpoints': [],
                'forms': [],
                'failed': [],
                'scripts': [],
                'skipped': [],
            },
            {},
            {},
        )
        self.assertIn('https://www.googletagmanager.com/gtm.js', anatomy['analytics'])
        self.assertIn('https://cdn.example.net/app.js', anatomy['cdn_assets'])
        self.assertIn('https://partner.example.org/readme', anatomy['external_refs'])
        self.assertIn('https://github.com/example/project', anatomy['trust_links'])

    def test_fixture_handler_send_accepts_binary_payloads(self):
        server = ThreadedHTTPServer(('127.0.0.1', 0), FixtureHandler)
        server.base_url = 'http://127.0.0.1:{}'.format(server.server_port)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        try:
            response = subprocess.run(
                ['python3', '-c', f'import urllib.request;print(urllib.request.urlopen("{server.base_url}/report.pdf").read()[:8].decode("latin1"))'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(response.returncode, 0, msg=response.stderr)
            self.assertIn('%PDF-1.4', response.stdout)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_archive_seeding_collects_from_multiple_sources(self):
        def fake_fetch(url, timeout=8, headers=None, proxies=None):
            parsed = urlsplit(url)
            query = parse_qs(parsed.query)
            archive_target = query.get('url', [''])[0]

            if url == 'https://index.commoncrawl.org/collinfo.json':
                return json.dumps([
                    {'id': 'CC-MAIN-2025-18'},
                    {'id': 'CC-MAIN-2025-13'},
                ])
            if parsed.netloc == 'web.archive.org' and archive_target == '*.example.com/*':
                return 'https://cdn.example.com/file\n'
            if parsed.netloc == 'web.archive.org' and archive_target == 'app.example.com/*':
                return 'https://app.example.com/alpha\nhttps://app.example.com/beta?b=2&a=1\n'
            if parsed.netloc == 'web.archive.org' and archive_target == 'example.com/*':
                return 'https://example.com/root\n'
            if parsed.netloc == 'index.commoncrawl.org' and parsed.path == '/CC-MAIN-2025-18-index' and archive_target == 'app.example.com/*':
                return '\n'.join([
                    json.dumps({'url': 'https://app.example.com/beta?a=1&b=2'}),
                    json.dumps({'url': 'https://app.example.com/gamma'}),
                ])
            return ''

        internal = set()
        with patch('core.zap._fetch', side_effect=fake_fetch):
            zap._archives('example.com', 'app.example.com', internal)

        self.assertIn('https://app.example.com/alpha', internal)
        self.assertIn('https://app.example.com/beta?a=1&b=2', internal)
        self.assertIn('https://app.example.com/gamma', internal)
        self.assertIn('https://example.com/root', internal)
        self.assertIn('https://cdn.example.com/file', internal)

    def test_robots_rules_return_crawl_delay(self):
        body = 'User-agent: *\nDisallow: /hidden\nCrawl-delay: 3\nSitemap: https://example.com/sitemap.xml\n'
        rules, sitemaps, crawl_delay = zap._applicable_robot_rules(body)
        self.assertEqual(rules, [('DISALLOW', '/hidden')])
        self.assertEqual(sitemaps, {'https://example.com/sitemap.xml'})
        self.assertEqual(crawl_delay, 3.0)

    def test_seed_from_robots_returns_rule_and_sitemap_metadata(self):
        internal = set()

        def fake_fetch(url, timeout=8, headers=None, proxies=None):
            if url.endswith('/robots.txt'):
                return 'User-agent: *\nAllow: /page\nDisallow: /hidden\nSitemap: https://example.com/sitemap.xml\n'
            if url.endswith('/sitemap.xml'):
                return '<urlset><url><loc>https://example.com/page</loc></url></urlset>'
            return ''

        with patch('core.zap._fetch', side_effect=fake_fetch):
            robots = set()
            metadata = zap._seed_from_robots(
                'https://example.com',
                False,
                'example.com',
                'example.com',
                internal,
                robots,
                [],
            )

        self.assertIn('https://example.com/page', internal)
        self.assertEqual(metadata['robots_rules'], [
            {'directive': 'ALLOW', 'path': '/page'},
            {'directive': 'DISALLOW', 'path': '/hidden'},
        ])
        self.assertIn('https://example.com/sitemap.xml', metadata['sitemap_urls'])
        self.assertEqual(metadata['sitemap_queued_urls'], ['https://example.com/page'])

    def test_checkpoint_round_trip_restores_sets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint = os.path.join(tmpdir, 'crawl.json')
            save_checkpoint(checkpoint, {
                'main_url': 'https://example.com',
                'stats': {'requests': 2, 'visited': 1},
                'internal': ['https://example.com'],
                'bad_intel': [[['secret', 'value'], 'TOKEN', 'https://example.com']],
            })
            restored = load_checkpoint(checkpoint)
            sets = normalize_checkpoint_sets(restored)
            self.assertEqual(restored['main_url'], 'https://example.com')
            self.assertIn('https://example.com', sets['internal'])
            self.assertIn((('secret', 'value'), 'TOKEN', 'https://example.com'), sets['bad_intel'])

    def test_render_page_collects_dom_and_network_urls(self):
        with patch('core.render._get_browser', return_value=FakeBrowser()):
            rendered = render.render_page('https://example.com', cookie='session=abc')
        self.assertIn('rendered-only', rendered.html)
        self.assertIn('https://example.com/rendered-only', rendered.urls)
        self.assertIn('https://example.com/graphql', rendered.urls)

    def test_politeness_controller_records_retry_after_backoff(self):
        controller = PolitenessController(base_delay=0, host_concurrency=1)
        controller.record_response('https://example.com', 429, {'Retry-After': '2'})
        state = controller._host_state('example.com')
        self.assertGreaterEqual(state['next_allowed'], time.time() + 1.5)

    def test_mode_helpers_extract_specialized_records(self):
        metadata, leaks = extract_document_records(
            'https://example.com/report.pdf',
            b'%PDF-1.4 /Author (Dracula) /Title (Night Ledger) analyst@example.com C:\\Users\\Vlad\\report.docx',
            'application/pdf',
        )
        self.assertTrue(any('author=Dracula' in item for item in metadata))
        self.assertTrue(any('analyst@example.com' in item for item in leaks))
        self.assertTrue(any('C:\\Users\\Vlad\\report.docx' in item for item in leaks))

        js_records = extract_js_intel(
            'https://example.com/app.js',
            'const betaCheckoutFlag=true; const runtimeConfig={"base":"/api"}; const token="sk_live_1234"; '
            'const view="AdminView"; const gtm="GTM-ABCD12"; const env=process.env.NEXT_PUBLIC_API_URL; '
            'console.error("old stack"); // ancient route retired',
        )
        self.assertTrue(any('feature=betaCheckoutFlag' in item for item in js_records))
        self.assertTrue(any('config=runtimeConfig' in item for item in js_records))
        self.assertTrue(any('view=AdminView' in item for item in js_records))
        self.assertTrue(any('analytics_id=' in item for item in js_records))
        self.assertTrue(any('env_hint=' in item for item in js_records))
        self.assertTrue(any('comment=' in item for item in js_records))

        thread_records = extract_thread_records(
            'https://example.com/thread',
            '<html><title>Night Thread</title><article class="post"><span class="author">CountZero</span>'
            '<blockquote>First omen rises.</blockquote>Reply from the dark.</article></html>',
        )
        self.assertTrue(any('thread=Night Thread' in item for item in thread_records))

        location_records = extract_location_records(
            'https://example.com/geo',
            '<html><head><meta name="geo.position" content="40.7128;-74.0060"></head>'
            '<body>Gathering in New York 40.7128, -74.0060</body></html>',
        )
        self.assertTrue(any('lat=40.7128' in item for item in location_records))
        self.assertTrue(any('label=New York' in item for item in location_records))

        story_records = extract_story_records(
            'https://example.com/news',
            '<html lang="en"><head><title>Vampire bats swarm the wires</title>'
            '<meta property="og:site_name" content="Night Wire">'
            '<meta property="article:published_time" content="2026-05-03T00:15:00Z"></head>'
            '<body>"Witnesses saw sparks in the abbey."<a href="https://mirror.example.net/story">mirror</a></body></html>',
        )
        self.assertTrue(any('story=vampire-bats-swarm-the-wires' in item for item in story_records))
        self.assertTrue(any('reference=https://mirror.example.net/story' in item for item in story_records))

        scam_records = extract_scam_signals(
            'https://example.com/offer',
            '<html><body>Limited time! Only 2 left. Offer ends in 03:00. Crypto only.</body></html>',
        )
        self.assertTrue(any('signal=FAKE_URGENCY' in item for item in scam_records))
        self.assertTrue(any('signal=PRESSURE_PAYMENT' in item for item in scam_records))

        hidden_candidates = build_hidden_candidates(
            'https://example.com',
            {'https://example.com/app'},
            {'https://example.com/static/app.js'},
            {'/api/crypt'},
        )
        self.assertIn('https://example.com/admin', hidden_candidates)

        diffs = build_temporal_diffs(
            {'internal': ['https://example.com/old'], 'stats': {'visited': 1}},
            {'internal': ['https://example.com/new'], 'stats': {'visited': 2}},
        )
        self.assertTrue(any('change=added value=https://example.com/new' in item for item in diffs))
        self.assertTrue(any('metric=visited before=1 after=2' in item for item in diffs))

    def test_launch_script_prompts_for_url_when_started_without_args(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_path = self._write_test_launcher(tmpdir)
            app_path = self._write_entrypoint_stub(tmpdir)
            bin_dir = self._write_python_stub(
                tmpdir,
                '#!/usr/bin/env bash\n'
                'if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then\n'
                '  exit 0\n'
                'fi\n'
                'printf "%s\\n" "$@" > "$TEST_LOG"\n',
            )

            env = os.environ.copy()
            env['PATH'] = bin_dir + os.pathsep + env.get('PATH', '')
            env['TEST_LOG'] = os.path.join(tmpdir, 'launch-args.txt')
            env['VAMPIRIC_LAUNCH_PROMPT'] = '1'

            result = subprocess.run(
                [launcher_path],
                cwd=tmpdir,
                input='https://example.com\n',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn('Enter target URL', result.stdout)

            with open(env['TEST_LOG'], 'r', encoding='utf-8') as handle:
                recorded_args = handle.read().splitlines()
            self.assertEqual(recorded_args, [app_path, '-u', 'https://example.com'])

    def test_launch_script_runs_setup_check_before_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_path = self._write_test_launcher(tmpdir)
            app_path = self._write_entrypoint_stub(tmpdir)
            bin_dir = self._write_python_stub(
                tmpdir,
                '#!/usr/bin/env bash\n'
                'if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then\n'
                '  exit 0\n'
                'fi\n'
                'printf "%s\\n" "$@" >> "$TEST_LOG"\n',
            )

            env = os.environ.copy()
            env['PATH'] = bin_dir + os.pathsep + env.get('PATH', '')
            env['TEST_LOG'] = os.path.join(tmpdir, 'launch-args.txt')
            env['VAMPIRIC_LAUNCH_PROMPT'] = '1'

            result = subprocess.run(
                [launcher_path],
                cwd=tmpdir,
                input='https://example.com\n',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            with open(env['TEST_LOG'], 'r', encoding='utf-8') as handle:
                recorded_args = handle.read().splitlines()
            self.assertEqual(recorded_args[:3], [app_path, '--setup-check', '-o'])
            self.assertEqual(recorded_args[-3:], [app_path, '-u', 'https://example.com'])

    def test_launch_script_trims_prompt_input_before_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_path = self._write_test_launcher(tmpdir)
            app_path = self._write_entrypoint_stub(tmpdir)
            bin_dir = self._write_python_stub(
                tmpdir,
                '#!/usr/bin/env bash\n'
                'if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then\n'
                '  exit 0\n'
                'fi\n'
                'printf "%s\\n" "$@" > "$TEST_LOG"\n',
            )

            env = os.environ.copy()
            env['PATH'] = bin_dir + os.pathsep + env.get('PATH', '')
            env['TEST_LOG'] = os.path.join(tmpdir, 'launch-args.txt')
            env['VAMPIRIC_LAUNCH_PROMPT'] = '1'

            result = subprocess.run(
                [launcher_path],
                cwd=tmpdir,
                input='   https://example.com/path   \n',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)

            with open(env['TEST_LOG'], 'r', encoding='utf-8') as handle:
                recorded_args = handle.read().splitlines()
            self.assertEqual(recorded_args, [app_path, '-u', 'https://example.com/path'])

    def test_launch_script_rejects_empty_prompt_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_path = self._write_test_launcher(tmpdir)
            self._write_entrypoint_stub(tmpdir)
            bin_dir = self._write_python_stub(tmpdir, '#!/usr/bin/env bash\nexit 0\n')

            env = os.environ.copy()
            env['PATH'] = bin_dir + os.pathsep + env.get('PATH', '')
            env['VAMPIRIC_LAUNCH_PROMPT'] = '1'

            result = subprocess.run(
                [launcher_path],
                cwd=tmpdir,
                input='\n',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn('Enter target URL', result.stdout)
            self.assertIn('No prey specified. Closing the coffin.', result.stderr)

    def test_launch_script_fails_cleanly_when_entrypoint_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            launcher_path = self._write_test_launcher(tmpdir)
            bin_dir = self._write_python_stub(tmpdir, '#!/usr/bin/env bash\nexit 0\n')

            env = os.environ.copy()
            env['PATH'] = bin_dir + os.pathsep + env.get('PATH', '')

            result = subprocess.run(
                [launcher_path, '-u', 'https://example.com'],
                cwd=tmpdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn('Missing entrypoint:', result.stderr)
            self.assertIn(os.path.join(tmpdir, 'vampire.py'), result.stderr)

    def test_cli_regression_for_headers_stats_redirects_forms_and_exports(self):
        FixtureHandler.header_failures = []
        FixtureHandler.flaky_hits = 0

        server = ThreadedHTTPServer(('127.0.0.1', 0), FixtureHandler)
        server.base_url = 'http://127.0.0.1:{}'.format(server.server_port)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_dir = os.path.join(tmpdir, 'loot')
                command = [
                    sys.executable,
                    os.path.join(REPO_ROOT, 'vampire.py'),
                    '-u', server.base_url,
                    '-l', '2',
                    '-t', '2',
                    '--timeout', '2',
                    '--respect-robots-delay',
                    '--host-concurrency', '1',
                    '-o', output_dir,
                    '-e', 'json',
                    '--stdout', 'stats',
                    '--keys',
                    '-H', 'X-Blood: moon',
                ]
                result = subprocess.run(
                    command,
                    cwd=REPO_ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 0, msg=result.stderr)
                self.assertEqual(FixtureHandler.header_failures, [])
                self.assertGreaterEqual(FixtureHandler.flaky_hits, 3)

                with open(os.path.join(output_dir, 'redirects.txt'), 'r', encoding='utf-8') as handle:
                    redirects = handle.read()
                self.assertIn('/redirect', redirects)
                self.assertIn('/landing', redirects)

                with open(os.path.join(output_dir, 'crawl-manifest.json'), 'r', encoding='utf-8') as handle:
                    manifest = json.load(handle)
                self.assertEqual(manifest['target']['main_url'], server.base_url + '/')
                self.assertEqual(manifest['lineage']['checkpoint_path'], '')
                self.assertIn('autopsy.json', manifest['artifacts'])
                self.assertIn('results.json', manifest['artifacts'])

                with open(os.path.join(output_dir, 'robots.txt'), 'r', encoding='utf-8') as handle:
                    robots = handle.read()
                self.assertIn('/hidden', robots)
                self.assertNotIn('/other-only', robots)

                with open(os.path.join(output_dir, 'internal.txt'), 'r', encoding='utf-8') as handle:
                    internal = handle.read()
                self.assertIn('/hidden', internal)
                self.assertIn('/sitemap-only', internal)
                self.assertIn('/sitemap-deep', internal)
                self.assertNotIn('/other-only', internal)
                self.assertIn('/openapi.json', internal)
                self.assertIn('/manifest.json', internal)

                with open(os.path.join(output_dir, 'skipped.txt'), 'r', encoding='utf-8') as handle:
                    skipped = handle.read()
                self.assertIn('/binary', skipped)

                with open(os.path.join(output_dir, 'forms.txt'), 'r', encoding='utf-8') as handle:
                    forms = handle.read()
                self.assertIn(f'action={server.base_url}/submit', forms)
                self.assertIn('method=POST', forms)
                self.assertIn('email:email', forms)
                self.assertIn('token:hidden', forms)

                with open(os.path.join(output_dir, 'fuzzable.txt'), 'r', encoding='utf-8') as handle:
                    fuzzable = handle.read().strip().splitlines()
                dup_fuzzables = [line for line in fuzzable if '/dup?' in line]
                self.assertEqual(dup_fuzzables, [server.base_url + '/dup?a=&b='])
                self.assertNotIn(server.base_url + '/dup?a=1&b=2', fuzzable)
                self.assertNotIn(server.base_url + '/dup?a=9&b=8', fuzzable)

                with open(os.path.join(output_dir, 'keys.txt'), 'r', encoding='utf-8') as handle:
                    keys = handle.read()
                self.assertIn('GITHUB_TOKEN', keys)

                with open(os.path.join(output_dir, 'intel.txt'), 'r', encoding='utf-8') as handle:
                    intel = handle.read()
                self.assertIn('EMAIL:test@example.com', intel)
                self.assertIn('discord.gg/nightshift', intel)

                with open(os.path.join(output_dir, 'endpoints.txt'), 'r', encoding='utf-8') as handle:
                    endpoints = handle.read()
                self.assertIn('/api/crypt', endpoints)
                self.assertIn('/graphql', endpoints)

                with open(os.path.join(output_dir, 'files.txt'), 'r', encoding='utf-8') as handle:
                    files = handle.read()
                self.assertIn('/script.js.map', files)
                self.assertIn('/openapi.json', files)
                self.assertIn('/manifest.json', files)

                with open(os.path.join(output_dir, 'stats.txt'), 'r', encoding='utf-8') as handle:
                    stats_file = handle.read()
                self.assertIn('redirects=', stats_file)
                self.assertIn('visited=', stats_file)

                with open(os.path.join(output_dir, 'results.json'), 'r', encoding='utf-8') as handle:
                    exported = json.load(handle)
                self.assertIn('stats', exported)
                self.assertIn('redirects', exported)
                self.assertIn('skipped', exported)
                self.assertIn('forms', exported)
                self.assertIsInstance(exported['stats'], dict)
                self.assertGreaterEqual(exported['stats']['redirects'], 1)

                with open(os.path.join(output_dir, 'autopsy.json'), 'r', encoding='utf-8') as handle:
                    autopsy = json.load(handle)
                self.assertEqual(autopsy['what_the_target_is']['ritual_chain'], 'domain_necropsy')
                self.assertIn('site_anatomy', autopsy)
                self.assertIn('mutation_engine', autopsy)
                self.assertIn('artifact_genealogy', autopsy)

                with open(os.path.join(output_dir, 'site_anatomy.txt'), 'r', encoding='utf-8') as handle:
                    anatomy = handle.read()
                self.assertIn('section=auth_surfaces', anatomy)
                self.assertIn('section=apis', anatomy)

                with open(os.path.join(output_dir, 'mutation_probes.txt'), 'r', encoding='utf-8') as handle:
                    mutations = handle.read()
                self.assertIn('/admin', mutations)

                with open(os.path.join(output_dir, 'artifact_genealogy.txt'), 'r', encoding='utf-8') as handle:
                    genealogy = handle.read()
                self.assertIn('/report.pdf', genealogy)

                self.assertIn('redirects=', result.stdout)
                self.assertIn('visited=', result.stdout)
                self.assertIn('Top types', result.stdout)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_cli_dry_run_reports_resolved_plan(self):
        result = subprocess.run(
            [
                sys.executable,
                os.path.join(REPO_ROOT, 'vampire.py'),
                '--target', 'example.com',
                '--preset', 'quick',
                '--dry-run',
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('Dry run', result.stdout)
        self.assertIn('Specimen type', result.stdout)
        self.assertIn('Preset', result.stdout)

    def test_cli_mode_runs_emit_specialized_datasets(self):
        FixtureHandler.header_failures = []
        FixtureHandler.flaky_hits = 0

        server = ThreadedHTTPServer(('127.0.0.1', 0), FixtureHandler)
        server.base_url = 'http://127.0.0.1:{}'.format(server.server_port)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                def run_mode(mode, output_dir, extra_args=None):
                    command = [
                        sys.executable,
                        os.path.join(REPO_ROOT, 'vampire.py'),
                        '-u', server.base_url,
                        '-l', '2',
                        '-t', '2',
                        '--timeout', '2',
                        '--mode', mode,
                        '-o', output_dir,
                        '-H', 'X-Blood: moon',
                    ]
                    if extra_args:
                        command.extend(extra_args)
                    result = subprocess.run(
                        command,
                        cwd=REPO_ROOT,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, msg=result.stderr)
                    return result

                js_output = os.path.join(tmpdir, 'js')
                run_mode('js-intel', js_output)
                self.assertIn('feature=betaCheckoutFlag', Path(js_output, 'js_intel.txt').read_text(encoding='utf-8'))
                self.assertIn('token=token', Path(js_output, 'js_intel.txt').read_text(encoding='utf-8'))

                doc_output = os.path.join(tmpdir, 'docs')
                run_mode('document', doc_output)
                self.assertIn('author=Dracula', Path(doc_output, 'document_metadata.txt').read_text(encoding='utf-8'))
                self.assertIn('archivist@example.com', Path(doc_output, 'document_leaks.txt').read_text(encoding='utf-8'))

                hidden_output = os.path.join(tmpdir, 'hidden')
                run_mode('hidden', hidden_output)
                self.assertIn('/admin', Path(hidden_output, 'hidden_paths.txt').read_text(encoding='utf-8'))

                forum_output = os.path.join(tmpdir, 'forum')
                run_mode('forum', forum_output)
                self.assertIn('Night Thread', Path(forum_output, 'threads.txt').read_text(encoding='utf-8'))

                geo_output = os.path.join(tmpdir, 'geo')
                run_mode('geo', geo_output)
                self.assertIn('lat=40.7128', Path(geo_output, 'locations.txt').read_text(encoding='utf-8'))

                news_output = os.path.join(tmpdir, 'news')
                run_mode('news', news_output)
                self.assertIn('story=vampire-bats-swarm-the-wires', Path(news_output, 'stories.txt').read_text(encoding='utf-8'))

                scam_output = os.path.join(tmpdir, 'scam')
                run_mode('scam', scam_output)
                self.assertIn('signal=FAKE_URGENCY', Path(scam_output, 'scam_signals.txt').read_text(encoding='utf-8'))

                baseline_dir = os.path.join(tmpdir, 'baseline')
                os.makedirs(baseline_dir)
                Path(baseline_dir, 'internal.txt').write_text(server.base_url + '/old\n', encoding='utf-8')
                Path(baseline_dir, 'stats.txt').write_text('visited=1\n', encoding='utf-8')
                temporal_output = os.path.join(tmpdir, 'temporal')
                run_mode('temporal', temporal_output, ['--temporal-baseline', baseline_dir])
                temporal_text = Path(temporal_output, 'temporal_diffs.txt').read_text(encoding='utf-8')
                self.assertIn('change=removed value=' + server.base_url + '/old', temporal_text)
                self.assertIn('metric=visited before=1', temporal_text)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_cli_can_resume_from_checkpoint(self):
        FixtureHandler.header_failures = []
        FixtureHandler.flaky_hits = 0

        server = ThreadedHTTPServer(('127.0.0.1', 0), FixtureHandler)
        server.base_url = 'http://127.0.0.1:{}'.format(server.server_port)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                checkpoint = os.path.join(tmpdir, 'crawl.json')
                seed_output = os.path.join(tmpdir, 'seed-loot')
                output_dir = os.path.join(tmpdir, 'loot')
                seed_only = subprocess.run(
                    [
                        sys.executable,
                        os.path.join(REPO_ROOT, 'vampire.py'),
                        '-u', server.base_url,
                        '-l', '0',
                        '--checkpoint', checkpoint,
                        '-o', seed_output,
                        '-H', 'X-Blood: moon',
                    ],
                    cwd=REPO_ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(seed_only.returncode, 0, msg=seed_only.stderr)
                state = load_checkpoint(checkpoint)
                self.assertEqual(state['stage'], 'complete')
                self.assertIn(server.base_url + '/', state['internal'])

                resumed = subprocess.run(
                    [
                        sys.executable,
                        os.path.join(REPO_ROOT, 'vampire.py'),
                        '--resume', checkpoint,
                        '-l', '2',
                        '-o', output_dir,
                        '-H', 'X-Blood: moon',
                    ],
                    cwd=REPO_ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(resumed.returncode, 0, msg=resumed.stderr)
                with open(os.path.join(output_dir, 'internal.txt'), 'r', encoding='utf-8') as handle:
                    internal = handle.read()
                self.assertIn('/page', internal)
                self.assertIn('/sitemap-only', internal)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_web_ui_build_crawl_command_maps_flags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, 'record')
            checkpoint = os.path.join(output_dir, 'checkpoint.json')
            os.makedirs(output_dir)
            command = build_crawl_command(
                {
                    'target_url': 'https://example.com',
                    'target_specimen': 'https://example.com',
                    'ritual_chain': 'dead_page_resurrection',
                    'mode': 'temporal',
                    'depth': 3,
                    'threads': 6,
                    'delay': 0.5,
                    'timeout': 9,
                    'scope': 'domain',
                    'extract_intel': False,
                    'extract_secrets': True,
                    'respect_robots_delay': True,
                    'render_js': True,
                    'archive_seeds': True,
                    'enumerate_subdomains': True,
                    'temporal_baseline': '/tmp/baseline',
                },
                output_dir=os.path.abspath(output_dir),
                checkpoint_path=os.path.abspath(checkpoint),
            )
        rendered = ' '.join(command)
        self.assertIn('--target https://example.com', rendered)
        self.assertIn('-l 3', rendered)
        self.assertIn('-t 6', rendered)
        self.assertIn('--scope domain', rendered)
        self.assertIn('--ritual-chain dead_page_resurrection', rendered)
        self.assertIn('--preset balanced', rendered)
        self.assertIn('--mode temporal', rendered)
        self.assertIn('--respect-robots-delay', rendered)
        self.assertIn('--render-js', rendered)
        self.assertIn('--wayback', rendered)
        self.assertIn('--dns', rendered)
        self.assertIn('--keys', rendered)
        self.assertIn('--only-urls', rendered)
        self.assertIn('--temporal-baseline /tmp/baseline', rendered)

    def test_cli_startup_handles_non_utf8_stdout(self):
        process = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, 'vampire.py')],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(os.environ, PYTHONIOENCODING='cp1252'),
            check=False,
        )
        stdout = process.stdout.decode('cp1252', errors='replace')
        stderr = process.stderr.decode('cp1252', errors='replace')
        self.assertEqual(process.returncode, 1)
        self.assertIn('Vampiric Crawler', stdout)
        self.assertIn('No prey specified', stdout)
        self.assertNotIn('UnicodeEncodeError', stdout)
        self.assertNotIn('UnicodeEncodeError', stderr)

    def test_web_ui_state_and_export_routes_surface_sealed_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(Path(tmpdir))
            manager = app.config['CRAWL_MANAGER']
            output_dir = Path(tmpdir) / 'record'
            output_dir.mkdir()
            checkpoint = output_dir / 'checkpoint.json'
            (output_dir / 'internal.txt').write_text('https://example.com/\nhttps://example.com/about\n', encoding='utf-8')
            (output_dir / 'files.txt').write_text('https://example.com/report.pdf\nhttps://example.com/app.js.map\n', encoding='utf-8')
            (output_dir / 'intel.txt').write_text('https://example.com:EMAIL:test@example.com\n', encoding='utf-8')
            (output_dir / 'failed.txt').write_text('https://example.com/admin\n', encoding='utf-8')
            (output_dir / 'redirects.txt').write_text('https://example.com/ => https://example.com/ -> https://example.com/about\n', encoding='utf-8')
            (output_dir / 'stats.txt').write_text('visited=2\nfailures=1\nredirects=0\n', encoding='utf-8')
            checkpoint.write_text(json.dumps({
                'version': 1,
                'queue_state': {
                    'pending': ['https://example.com/contact'],
                    'active': ['https://example.com/about'],
                    'completed': ['https://example.com/'],
                    'skipped': ['https://example.com/report.pdf'],
                },
                'crawl_records': {
                    'https://example.com/': {
                        'url': 'https://example.com/',
                        'status_code': 200,
                        'content_type': 'text/html',
                        'depth': 1,
                        'source_page': 'seed',
                        'discovery_time': 1,
                        'state': 'completed',
                        'source_kind': 'seed',
                    },
                },
                'robots_metadata': {
                    'rules': [{'directive': 'DISALLOW', 'path': '/hidden'}],
                    'crawl_delay': 1,
                },
                'sitemap_metadata': {
                    'sitemap_urls': ['https://example.com/sitemap.xml'],
                    'queued_urls': ['https://example.com/about'],
                },
            }), encoding='utf-8')
            manager.current_run = CrawlRun(
                run_id='sealed-record',
                payload={'target_url': 'https://example.com', 'depth': 2, 'threads': 4, 'mode': 'document'},
                output_dir=output_dir,
                checkpoint_path=checkpoint,
                command=[sys.executable, os.path.join(REPO_ROOT, 'vampire.py')],
                status='complete',
                status_detail='CRAWL SEALED',
                ended_at='2026-05-03T09:16:06+00:00',
            )

            with app.test_client() as client:
                state_response = client.get('/api/state')
                self.assertEqual(state_response.status_code, 200)
                state_data = state_response.get_json()
                self.assertEqual(state_data['status'], 'complete')
                self.assertEqual(state_data['mode'], 'document')
                self.assertEqual(state_data['summary']['mode_label'], 'Document harvester')
                self.assertEqual(state_data['summary']['document_tombs'], 1)
                self.assertEqual(state_data['summary']['mail_sigils'], 1)
                self.assertTrue(any(panel['key'] == 'documents' for panel in state_data['panels']))
                self.assertTrue(any(item['kind'] == 'autopsy-md' for item in state_data['exports']))
                self.assertTrue(any(item['kind'] == 'manifest-json' for item in state_data['exports']))
                self.assertTrue(any(item['kind'] == 'bundle' for item in state_data['exports']))
                self.assertEqual(state_data['queue']['pending']['count'], 1)
                self.assertEqual(state_data['robots_details']['crawl_delay'], 1)
                self.assertEqual(state_data['sitemap_details']['sitemap_urls'], ['https://example.com/sitemap.xml'])
                self.assertEqual(state_data['result_rows'][0]['source_page'], 'seed')
                self.assertEqual(state_data['result_rows'][0]['source_kind'], 'seed')
                self.assertEqual(state_data['result_rows'][0]['related_panel_key'], 'links')
                self.assertEqual(state_data['result_rows'][0]['redirect_chain'], ['https://example.com/', 'https://example.com/about'])

                autopsy_response = client.get('/api/exports/autopsy-md')
                self.assertEqual(autopsy_response.status_code, 200)
                self.assertIn('Vampiric Crawler Autopsy', autopsy_response.get_data(as_text=True))
                autopsy_response.close()

                manifest_response = client.get('/api/exports/manifest-json')
                self.assertEqual(manifest_response.status_code, 200)
                manifest_payload = json.loads(manifest_response.get_data(as_text=True))
                self.assertEqual(manifest_payload['target']['main_url'], 'https://example.com')
                manifest_response.close()

                bundle_response = client.get('/api/exports/bundle')
                self.assertEqual(bundle_response.status_code, 200)
                bundle_response.close()

    def test_web_ui_setup_check_route_surfaces_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(Path(tmpdir))
            with patch('webapp.setup_status', return_value={
                'packages': {'flask': 'ok', 'playwright': 'missing: browser'},
                'playwright_browser': 'missing: browser',
                'render_smoke': 'missing: browser',
                'output_dir': {'path': tmpdir, 'status': 'ok'},
                'proxy': {'status': 'not-configured', 'detail': 'No proxy configured for setup check.'},
                'install_hint': 'python -m pip install -r requirements.txt',
                'browser_hint': 'python -m playwright install chromium',
            }):
                with app.test_client() as client:
                    response = client.get('/api/setup-check')
                    self.assertEqual(response.status_code, 200)
                    payload = response.get_json()
                    self.assertEqual(payload['overall_status'], 'issues')
                    self.assertTrue(any(item['name'] == 'render-smoke' for item in payload['checks']))


if __name__ == '__main__':
    unittest.main()
