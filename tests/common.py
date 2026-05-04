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
    build_hidden_candidate_records,
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

    def screenshot(self, full_page=True, type='png'):
        return b'\x89PNG\r\n\x1a\nfake'


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



class RegressionTestCase(unittest.TestCase):
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
