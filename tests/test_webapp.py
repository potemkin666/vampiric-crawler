from common import *


class WebAppTests(RegressionTestCase):
    def test_web_ui_flag_controls_use_semantic_grouping(self):
        template = Path(REPO_ROOT, 'templates', 'index.html').read_text(encoding='utf-8')
        stylesheet = Path(REPO_ROOT, 'static', 'webui.css').read_text(encoding='utf-8')
        self.assertIn('<fieldset class="flag-fieldset" aria-describedby="flagHelp">', template)
        self.assertIn('<legend>SCOPE AND EXTRACTION FLAGS</legend>', template)
        self.assertIn('id="flagStatus" aria-live="polite" aria-atomic="true"', template)
        self.assertNotIn('[X] EXTRACT MAIL SIGILS', template)
        self.assertIn('.sr-only {', stylesheet)
        self.assertIn('.flag-fieldset {', stylesheet)

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
                    'hidden_words': ['vault', 'attic'],
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
        self.assertIn('--hidden-word vault', rendered)

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
                self.assertEqual(manifest_payload['run_metadata']['run_id'], 'sealed-record')
                manifest_response.close()

                bundle_response = client.get('/api/exports/bundle')
                self.assertEqual(bundle_response.status_code, 200)
                bundle_response.close()

                manager.current_run = None
                manager.history.appendleft({
                    'id': 'sealed-record',
                    'target_url': 'https://example.com',
                    'mode': 'document',
                    'ended_at': '2026-05-03T09:16:06+00:00',
                    'status': 'complete',
                    'status_message': 'CRAWL SEALED',
                    'output_dir': str(output_dir),
                    'state_href': '/api/runs/sealed-record',
                    'exports': [],
                })
                historical_response = client.get('/api/runs/sealed-record')
                self.assertEqual(historical_response.status_code, 200)
                historical_payload = historical_response.get_json()
                self.assertTrue(historical_payload['is_historical'])
                self.assertEqual(historical_payload['id'], 'sealed-record')
                self.assertTrue(any(item['href'].startswith('/api/runs/sealed-record/exports/') for item in historical_payload['exports']))

                historical_manifest = client.get('/api/runs/sealed-record/exports/manifest-json')
                self.assertEqual(historical_manifest.status_code, 200)
                historical_manifest.close()

    def test_web_ui_temporal_mode_requires_explicit_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(Path(tmpdir))
            with app.test_client() as client:
                response = client.post('/api/crawl', json={
                    'target_specimen': 'https://example.com',
                    'target_url': 'https://example.com',
                    'mode': 'temporal',
                })
                self.assertEqual(response.status_code, 400)
                payload = response.get_json()
                self.assertIn('Temporal mode requires an explicit baseline path.', payload['error'])

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
