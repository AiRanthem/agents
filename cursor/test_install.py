"""Cloud-agent install replaces its ~/.cursor copies on every run."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import install


class ReplaceInstallTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()

    def test_install_copies_rules_agents_and_skills(self):
        install.install(self.home)
        for source, dest in (
            (install.DIRECTORY / 'rules/agents.mdc', self.home / '.cursor/rules/agents.mdc'),
            (install.DIRECTORY / 'agents/composer.md', self.home / '.cursor/agents/composer.md'),
            (install.ROOT / 'skills/advance-project/SKILL.md',
             self.home / '.cursor/skills/advance-project/SKILL.md'),
        ):
            self.assertFalse(dest.is_symlink(), dest)
            self.assertEqual(dest.read_bytes(), source.read_bytes())
        for skill in install.skill_directories():
            self.assertEqual(
                (self.home / '.cursor/skills' / skill.name / 'SKILL.md').read_bytes(),
                (skill / 'SKILL.md').read_bytes())
        self.assertFalse((self.home / '.agents').exists())
        self.assertFalse((self.home / '.cursor/statusline.sh').exists())
        self.assertFalse((self.home / '.cursor/cli-config.json').exists())

    def test_rerun_replaces_previous_copies_and_drops_removed_names(self):
        install.install(self.home)
        cursor = self.home / '.cursor'
        (cursor / 'rules/agents.mdc').write_text('stale rule')
        (cursor / 'rules/removed.mdc').write_text('removed rule')
        removed = cursor / 'skills/removed-skill'
        removed.mkdir()
        (removed / 'SKILL.md').write_text('removed skill')
        sentinel = cursor / 'skills-cursor/keep'
        sentinel.parent.mkdir()
        sentinel.write_text('keep')
        statusline = cursor / 'statusline.sh'
        statusline.write_text('leave cli alone')
        install.install(self.home)
        self.assertEqual(
            (cursor / 'rules/agents.mdc').read_bytes(),
            (install.DIRECTORY / 'rules/agents.mdc').read_bytes())
        self.assertFalse((cursor / 'rules/removed.mdc').exists())
        self.assertFalse(removed.exists())
        self.assertEqual(sentinel.read_text(), 'keep')
        self.assertEqual(statusline.read_text(), 'leave cli alone')
        self.assertFalse((self.home / '.agents').exists())

    def test_cli_uses_home(self):
        result = subprocess.run(
            [sys.executable, '-S', str(install.DIRECTORY / 'install.py')],
            text=True, capture_output=True, timeout=30,
            env={'HOME': str(self.home), 'PATH': '/usr/bin:/bin'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / '.cursor/rules/agents.mdc').is_file())
        self.assertFalse((self.home / '.agents').exists())


if __name__ == '__main__':
    unittest.main()
