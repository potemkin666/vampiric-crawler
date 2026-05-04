from common import *


class LauncherTests(RegressionTestCase):
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


if __name__ == '__main__':
    unittest.main()
