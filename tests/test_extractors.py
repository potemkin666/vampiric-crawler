from common import *


class ExtractorTests(RegressionTestCase):
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
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.render._get_browser', return_value=FakeBrowser()):
                rendered = render.render_page('https://example.com', cookie='session=abc', evidence_dir=tmpdir)
            self.assertIn('rendered-only', rendered.html)
            self.assertIn('https://example.com/rendered-only', rendered.urls)
            self.assertIn('https://example.com/graphql', rendered.urls)
            self.assertTrue(rendered.dom_sha256)
            self.assertTrue(rendered.screenshot_path.endswith('.png'))
            self.assertTrue(os.path.exists(rendered.screenshot_path))
            self.assertTrue(rendered.metadata_path.endswith('.json'))
            with open(rendered.metadata_path, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
            self.assertEqual(payload['requested_url'], 'https://example.com')
            self.assertEqual(payload['dom_sha256'], rendered.dom_sha256)

    def test_politeness_controller_records_retry_after_backoff(self):
        controller = PolitenessController(base_delay=0, host_concurrency=1)
        controller.record_response('https://example.com', 429, {'Retry-After': '2'})
        state = controller._host_state('example.com')
        self.assertGreaterEqual(state['next_allowed'], time.time() + 1.5)


if __name__ == '__main__':
    unittest.main()
