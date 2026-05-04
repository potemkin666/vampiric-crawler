from common import *


class CliTests(RegressionTestCase):
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
                self.assertIn('run_metadata', manifest)

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
                self.assertIn('run_metadata', autopsy)
                self.assertEqual(autopsy['run_metadata']['run_id'], manifest['run_metadata']['run_id'])
                self.assertIn('saved_at', autopsy['run_metadata'])
                self.assertIn('command_line', autopsy['run_metadata'])
                self.assertIn('python_version', autopsy['run_metadata']['runtime'])

                with open(os.path.join(output_dir, 'temporal-baseline.json'), 'r', encoding='utf-8') as handle:
                    structured_snapshot = json.load(handle)
                self.assertIn('artifact_genealogy', structured_snapshot)
                self.assertIn('content_types', structured_snapshot)
                self.assertIn('report_metadata', structured_snapshot)

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
                run_mode('hidden', hidden_output, ['--hidden-word', 'vault'])
                self.assertIn('strategy=', Path(hidden_output, 'hidden_paths.txt').read_text(encoding='utf-8'))
                self.assertIn('token=vault', Path(hidden_output, 'hidden_probe_sources.txt').read_text(encoding='utf-8'))

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
                Path(baseline_dir, 'autopsy.json').write_text(json.dumps({
                    'artifact_genealogy': {
                        server.base_url + '/report.pdf': {
                            'sha256': 'oldhash',
                            'content_type': 'application/pdf',
                            'size': 12,
                            'archive_presence': False,
                        },
                    },
                    'run_summary': {
                        'top_content_types': [['text/html', 1]],
                    },
                    'run_metadata': {
                        'command_line': 'python old-run',
                        'baseline_source': baseline_dir,
                        'flags': {'render_js': True},
                        'runtime': {'python_version': '3.11.0', 'git_commit': 'deadbeef'},
                    },
                    'what_the_target_is': {
                        'mode': 'temporal',
                        'preset': 'balanced',
                        'ritual_chain': 'dead_page_resurrection',
                    },
                }), encoding='utf-8')
                Path(baseline_dir, 'crawl-manifest.json').write_text(json.dumps({
                    'target': {
                        'mode': 'temporal',
                        'preset': 'balanced',
                        'ritual_chain': 'dead_page_resurrection',
                    },
                    'artifacts': {
                        'autopsy.json': {'sha256': 'manifesthash', 'size': 111},
                    },
                    'run_metadata': {
                        'command_line': 'python old-run',
                        'baseline_source': baseline_dir,
                        'flags': {'render_js': True},
                        'runtime': {'python_version': '3.11.0', 'git_commit': 'deadbeef'},
                    },
                }), encoding='utf-8')
                temporal_output = os.path.join(tmpdir, 'temporal')
                run_mode('temporal', temporal_output, ['--temporal-baseline', baseline_dir])
                temporal_text = Path(temporal_output, 'temporal_diffs.txt').read_text(encoding='utf-8')
                self.assertIn('change=removed value=' + server.base_url + '/old', temporal_text)
                self.assertIn('metric=visited before=1', temporal_text)
                self.assertIn('dataset=artifact_genealogy item=' + server.base_url + '/report.pdf field=sha256', temporal_text)
                self.assertIn('dataset=report_metadata metric=command_line before=python old-run', temporal_text)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_cli_default_output_dir_uses_timestamped_run_folder(self):
        FixtureHandler.header_failures = []
        FixtureHandler.flaky_hits = 0

        server = ThreadedHTTPServer(('127.0.0.1', 0), FixtureHandler)
        server.base_url = 'http://127.0.0.1:{}'.format(server.server_port)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    [
                        sys.executable,
                        os.path.join(REPO_ROOT, 'vampire.py'),
                        '-u', server.base_url,
                        '-l', '0',
                        '-t', '1',
                        '--timeout', '2',
                    ],
                    cwd=tmpdir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                runs_root = Path(tmpdir, 'sealed-runs')
                run_dirs = [item for item in runs_root.iterdir() if item.is_dir()]
                self.assertEqual(len(run_dirs), 1)
                self.assertTrue(run_dirs[0].name.endswith('-generic'))
                self.assertTrue(Path(run_dirs[0], 'stats.txt').exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_temporal_mode_requires_explicit_baseline(self):
        result = subprocess.run(
            [
                sys.executable,
                os.path.join(REPO_ROOT, 'vampire.py'),
                '--target', 'example.com',
                '--mode', 'temporal',
                '--dry-run',
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('Temporal mode requires an explicit --temporal-baseline path.', result.stdout)

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


if __name__ == '__main__':
    unittest.main()
