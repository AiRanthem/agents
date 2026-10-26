"""First-install behavior in disposable Cursor homes."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import install


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()

    def test_fresh_install_links_repository_and_checks_statusline(self):
        result = install.install(self.home)
        self.assertEqual(result['status'], 'disk_ready')
        self.assertFalse(result['runtime_verified'])
        self.assertGreater(result['created'], 0)
        for source in install.shared_skills():
            for root in ('.cursor/skills', '.agents/skills'):
                link = self.home / root / source.name
                self.assertTrue(link.is_symlink(), link)
                self.assertEqual(link.resolve(), source)
                self.assertTrue((link / 'SKILL.md').is_file())
        for source in (install.DIRECTORY / 'rules').glob('*.mdc'):
            link = self.home / '.cursor/rules' / source.name
            self.assertEqual(link.resolve(), source.resolve())
        for source in (install.DIRECTORY / 'agents').glob('*.md'):
            link = self.home / '.cursor/agents' / source.name
            self.assertEqual(link.resolve(), source.resolve())
        statusline = self.home / '.cursor/statusline.sh'
        self.assertEqual(statusline.resolve(), (install.DIRECTORY / 'statusline.sh').resolve())
        config = json.loads((self.home / '.cursor/cli-config.json').read_text())
        self.assertEqual(config['steering'], False)
        self.assertEqual(config['statusLine']['command'], '~/.cursor/statusline.sh')
        sample = subprocess.run(
            [str(statusline)],
            input=install.STATUSLINE_SAMPLE,
            text=True,
            capture_output=True,
            timeout=15,
            env={**os.environ, 'HOME': str(self.home)},
            check=False,
        )
        self.assertIn('Opus', sample.stdout)

    def test_repeat_and_seeded_config_keep_unrelated_entries(self):
        cursor = self.home / '.cursor'
        cursor.mkdir()
        (cursor / 'cli-config.json').write_text('{"editor":{"vimMode":true}}\n')
        local_rule = cursor / 'rules/local.mdc'
        local_rule.parent.mkdir()
        local_rule.write_text('local rule')
        sentinel = cursor / 'skills-cursor/keep'
        sentinel.parent.mkdir()
        sentinel.write_text('keep')
        install.install(self.home)
        config_path = cursor / 'cli-config.json'
        config = json.loads(config_path.read_text())
        self.assertEqual(config['editor'], {'vimMode': True})
        self.assertEqual(config['statusLine']['type'], 'command')
        before = config_path.read_bytes()
        again = install.install(self.home)
        self.assertEqual(again['created'], 0)
        self.assertEqual(config_path.read_bytes(), before)
        self.assertEqual(local_rule.read_text(), 'local rule')
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_conflicts_fail_before_creating_links(self):
        cursor = self.home / '.cursor'
        cursor.mkdir()
        rule = cursor / 'rules/agents.mdc'
        rule.parent.mkdir()
        rule.write_text('local rule')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            install.install(self.home)
        self.assertEqual(rule.read_text(), 'local rule')
        self.assertFalse((self.home / '.agents').exists())
        self.assertFalse((cursor / 'skills').exists())
        rule.unlink()

        foreign = self.home / '.cursor/skills/advance-project'
        foreign.mkdir(parents=True)
        (foreign / 'SKILL.md').write_text('local skill')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            install.install(self.home)
        self.assertEqual((foreign / 'SKILL.md').read_text(), 'local skill')
        self.assertFalse((self.home / '.agents').exists())

        config = cursor / 'cli-config.json'
        config.write_text('{"steering": true}\n')
        foreign.rename(foreign.parent / 'foreign-skill')
        with self.assertRaisesRegex(ValueError, 'differs'):
            install.install(self.home)
        self.assertEqual(json.loads(config.read_text())['steering'], True)
        self.assertFalse((self.home / '.agents').exists())

    def test_redirected_parent_is_rejected(self):
        redirected = self.home / '.cursor'
        redirected.symlink_to(self.home / 'other', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'ordinary directory'):
            install.install(self.home)
        self.assertFalse((self.home / '.agents').exists())
        self.assertFalse((self.home / 'other').exists())

    def test_explicit_home_cli_is_idempotent(self):
        command = [sys.executable, '-S', str(install.DIRECTORY / 'install.py'), '--home', str(self.home)]
        result = subprocess.run(command, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'disk_ready')
        result = subprocess.run(command, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['created'], 0)


if __name__ == '__main__':
    unittest.main()
