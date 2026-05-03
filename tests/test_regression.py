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
from core.politeness import PolitenessController
from core.utils import (
    extract_headers,
    is_in_scope,
    normalize_fuzzable_url,
    normalize_url,
    top_level,
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
        encoded = body.encode('utf-8')
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
                'const api="/api/crypt"; fetch("/graphql"); //# sourceMappingURL=/script.js.map',
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

                self.assertIn('redirects=', result.stdout)
                self.assertIn('visited=', result.stdout)
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
                },
                output_dir=os.path.abspath(output_dir),
                checkpoint_path=os.path.abspath(checkpoint),
            )
        rendered = ' '.join(command)
        self.assertIn('-u https://example.com', rendered)
        self.assertIn('-l 3', rendered)
        self.assertIn('-t 6', rendered)
        self.assertIn('--scope domain', rendered)
        self.assertIn('--respect-robots-delay', rendered)
        self.assertIn('--render-js', rendered)
        self.assertIn('--wayback', rendered)
        self.assertIn('--dns', rendered)
        self.assertIn('--keys', rendered)
        self.assertIn('--only-urls', rendered)

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
            (output_dir / 'stats.txt').write_text('visited=2\nfailures=1\nredirects=0\n', encoding='utf-8')
            manager.current_run = CrawlRun(
                run_id='sealed-record',
                payload={'target_url': 'https://example.com', 'depth': 2, 'threads': 4},
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
                self.assertEqual(state_data['summary']['document_tombs'], 1)
                self.assertEqual(state_data['summary']['mail_sigils'], 1)
                self.assertTrue(any(item['kind'] == 'report' for item in state_data['exports']))

                report_response = client.get('/api/exports/report')
                self.assertEqual(report_response.status_code, 200)
                self.assertIn('SEALED RECORD', report_response.get_data(as_text=True))
                report_response.close()


if __name__ == '__main__':
    unittest.main()
