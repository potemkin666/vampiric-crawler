import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from core.utils import (
    extract_headers,
    is_in_scope,
    normalize_fuzzable_url,
    normalize_url,
)
from plugins.exporter import exporter

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
        elif self.path.startswith('/dup'):
            self._send(200, '<html><body>duplicate</body></html>')
        elif self.path == '/landing':
            self._send(200, '<html><body>landed</body></html>')
        elif self.path == '/redirect':
            self._send(302, '', headers={'Location': base_url + '/landing'})
        elif self.path == '/binary':
            self._send(200, '%PDF-1.4', content_type='application/pdf')
        elif self.path == '/script.js':
            self._send(200, 'const api="/api/crypt";', content_type='application/javascript')
        elif self.path == '/submit':
            self._send(200, '<html><body>submitted</body></html>')
        elif self.path == '/flaky':
            FixtureHandler.flaky_hits += 1
            if FixtureHandler.flaky_hits < 3:
                self._send(500, 'try again', content_type='text/plain')
            else:
                self._send(200, '<html><body>stable now</body></html>')
        elif self.path == '/robots.txt':
            self._send(200, 'Allow: /page\nAllow: /flaky\n', content_type='text/plain')
        elif self.path == '/sitemap.xml':
            body = '<urlset><url><loc>{}/redirect</loc></url></urlset>'.format(base_url)
            self._send(200, body, content_type='application/xml')
        else:
            self._send(404, 'missing', content_type='text/plain')

    def log_message(self, format, *args):
        return


class RegressionTests(unittest.TestCase):
    def test_url_normalization_helpers(self):
        self.assertEqual(
            normalize_url('HTTPS://Example.com//a/../dup/?b=2&a=1#frag'),
            'https://example.com/dup?a=1&b=2',
        )
        self.assertEqual(
            normalize_fuzzable_url('https://example.com/dup?b=2&a=1&a=9'),
            'https://example.com/dup?a=&b=',
        )
        self.assertTrue(is_in_scope('https://api.example.com/path', 'www.example.com', 'example.com', 'domain'))
        self.assertFalse(is_in_scope('https://api.example.com/path', 'www.example.com', 'example.com', 'host'))

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

                with open(os.path.join(output_dir, 'skipped.txt'), 'r', encoding='utf-8') as handle:
                    skipped = handle.read()
                self.assertIn('/binary', skipped)

                with open(os.path.join(output_dir, 'forms.txt'), 'r', encoding='utf-8') as handle:
                    forms = handle.read()
                self.assertIn('action=', forms)
                self.assertIn('method=POST', forms)
                self.assertIn('email:email', forms)

                with open(os.path.join(output_dir, 'fuzzable.txt'), 'r', encoding='utf-8') as handle:
                    fuzzable = handle.read().strip().splitlines()
                dup_fuzzables = [line for line in fuzzable if '/dup?' in line]
                self.assertEqual(dup_fuzzables, [server.base_url + '/dup?a=&b='])

                with open(os.path.join(output_dir, 'keys.txt'), 'r', encoding='utf-8') as handle:
                    keys = handle.read()
                self.assertIn('GITHUB_TOKEN', keys)

                with open(os.path.join(output_dir, 'intel.txt'), 'r', encoding='utf-8') as handle:
                    intel = handle.read()
                self.assertIn('EMAIL:test@example.com', intel)
                self.assertIn('discord.gg/nightshift', intel)

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


if __name__ == '__main__':
    unittest.main()
