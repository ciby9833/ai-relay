"""Regression tests for the publication guard; only synthetic credentials are used."""
import contextlib
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import check_release


class ReleaseGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.root_patch = patch.object(check_release, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)

    def scan(self, history=False):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['check_release'] + (['--history'] if history else [])), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = check_release.main()
        return result, output.getvalue()

    def test_safe_template_and_source_pass(self):
        (self.root / '.env.example').write_text('SECRET_KEY=\n')
        (self.root / 'main.py').write_text('print("hello")\n')
        self.git('add', '.')
        self.assertEqual(self.scan()[0], 0)

    def test_staged_secret_is_blocked_even_after_worktree_is_cleaned(self):
        secret = 'synthetic-' + 'credential-value-for-test'
        (self.root / '.env').write_text('SECRET_KEY=' + secret)
        (self.root / 'main.py').write_text('value = ' + repr(secret))
        self.git('add', 'main.py')
        (self.root / 'main.py').write_text('value = None')
        result, output = self.scan()
        self.assertEqual(result, 1)
        self.assertNotIn(secret, output)

    def test_deleted_historical_secret_is_blocked(self):
        (self.root / 'credentials.txt').write_text('gh' + 'p_' + 'x' * 30)
        self.git('add', '.')
        self.git('commit', '-qm', 'unsafe history')
        self.git('rm', 'credentials.txt')
        self.git('commit', '-qm', 'remove')
        self.assertEqual(self.scan()[0], 0)
        self.assertEqual(self.scan(history=True)[0], 1)

    def test_private_paths_and_symlinks_are_blocked(self):
        for name in ('.env.production', 'backup.sql', 'identity.pem'):
            (self.root / name).write_text('synthetic')
        (self.root / 'linked').symlink_to('/outside/project')
        self.git('add', '.')
        result, output = self.scan()
        self.assertEqual(result, 1)
        for name in ('.env.production', 'backup.sql', 'identity.pem', 'linked'):
            self.assertIn(name, output)


if __name__ == '__main__':
    unittest.main()
